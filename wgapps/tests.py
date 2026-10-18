from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from wgapps.models import FeedbackSubmission
from wgapps.tasks import FeedbackDeliveryError, claim_next_feedback, deliver_feedback


class FeedbackSubmitViewTests(TestCase):
    def valid_payload(self):
        return {
            "name": "Анна",
            "phone": "7 (999) 123-45-67",
            "message": "Хочу записаться",
            "source": "Стоимость консультации",
            "contact_method": ["Telegram", "Телефон"],
            "telegram_username": "@anna",
        }

    @patch("wgapps.tasks.urllib.request.urlopen")
    def test_submission_is_saved_without_network_request(self, urlopen):
        response = self.client.post(reverse("feedback_submit"), self.valid_payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        submission = FeedbackSubmission.objects.get()
        self.assertEqual(submission.name, "Анна")
        self.assertEqual(submission.contact_method, "Telegram, Телефон")
        self.assertEqual(submission.attempt_count, 0)
        self.assertIsNone(submission.next_attempt_at)
        urlopen.assert_not_called()

    @patch("wgapps.views.FeedbackSubmission.objects.create", side_effect=RuntimeError("database unavailable"))
    def test_database_error_is_reported(self, create):
        response = self.client.post(reverse("feedback_submit"), self.valid_payload())

        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(FeedbackSubmission.objects.count(), 0)
        create.assert_called_once()

    def test_too_long_value_is_rejected_before_saving(self):
        payload = self.valid_payload()
        payload["name"] = "А" * 121

        response = self.client.post(reverse("feedback_submit"), payload)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(FeedbackSubmission.objects.count(), 0)


@override_settings(
    GOOGLE_FORM_ID="form-id",
    GOOGLE_ENTRY_NAME="entry.1",
    GOOGLE_ENTRY_PHONE="entry.2",
    TELEGRAM_BOT_TOKEN="bot-token",
    TELEGRAM_CHAT_ID="chat-id",
    FEEDBACK_RETRY_INITIAL_SECONDS=60,
    FEEDBACK_RETRY_MAX_SECONDS=3600,
)
class FeedbackDeliveryTaskTests(TestCase):
    def create_submission(self, **overrides):
        values = {
            "name": "Анна",
            "phone": "+79991234567",
            "message": "Сообщение",
            "source": "Главная",
            "contact_method": "Telegram",
            "telegram_username": "@anna",
        }
        values.update(overrides)
        return FeedbackSubmission.objects.create(**values)

    @patch("wgapps.tasks._send_to_telegram")
    @patch("wgapps.tasks._send_to_google")
    def test_successful_delivery_updates_all_channels(self, send_to_google, send_to_telegram):
        submission = self.create_submission()

        result = deliver_feedback(submission.pk)

        submission.refresh_from_db()
        self.assertEqual(result["status"], "delivered")
        self.assertEqual(submission.attempt_count, 1)
        self.assertIsNotNone(submission.google_sent_at)
        self.assertIsNotNone(submission.telegram_sent_at)
        self.assertIsNotNone(submission.delivered_at)
        self.assertEqual(submission.last_error, "")
        send_to_google.assert_called_once()
        send_to_telegram.assert_called_once()

    @patch("wgapps.tasks._send_to_telegram")
    @patch("wgapps.tasks._send_to_google")
    def test_partial_delivery_schedules_retry_without_resending_successful_channel(
        self,
        send_to_google,
        send_to_telegram,
    ):
        submission = self.create_submission()
        send_to_telegram.side_effect = FeedbackDeliveryError("Telegram недоступен")

        result = deliver_feedback(submission.pk)

        submission.refresh_from_db()
        self.assertEqual(result["status"], "retry_scheduled")
        self.assertIsNotNone(submission.google_sent_at)
        self.assertIsNone(submission.telegram_sent_at)
        self.assertIsNone(submission.delivered_at)
        self.assertIsNotNone(submission.next_attempt_at)
        self.assertIn("Telegram недоступен", submission.last_error)

        send_to_google.reset_mock()
        send_to_telegram.reset_mock()
        send_to_telegram.side_effect = None

        retry_result = deliver_feedback(submission.pk)

        submission.refresh_from_db()
        self.assertEqual(retry_result["status"], "delivered")
        self.assertEqual(submission.attempt_count, 2)
        self.assertIsNotNone(submission.telegram_sent_at)
        self.assertIsNotNone(submission.delivered_at)
        send_to_google.assert_not_called()
        send_to_telegram.assert_called_once()

    @override_settings(FEEDBACK_DELIVERY_MAX_ATTEMPTS=1)
    @patch("wgapps.tasks._send_to_telegram")
    @patch("wgapps.tasks._send_to_google")
    def test_last_failed_attempt_is_recorded_without_another_retry(
        self,
        send_to_google,
        send_to_telegram,
    ):
        submission = self.create_submission()
        send_to_google.side_effect = FeedbackDeliveryError("Google недоступен")
        send_to_telegram.side_effect = FeedbackDeliveryError("Telegram недоступен")
        submission_id = claim_next_feedback()

        with self.assertRaises(FeedbackDeliveryError):
            deliver_feedback(submission_id)

        submission.refresh_from_db()
        self.assertEqual(submission.attempt_count, 1)
        self.assertIn("Google недоступен", submission.last_error)
        self.assertIn("Telegram недоступен", submission.last_error)
        self.assertIsNone(submission.next_attempt_at)

    @override_settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    @patch("wgapps.tasks._send_to_telegram")
    @patch("wgapps.tasks._send_to_google")
    def test_telegram_is_optional_when_not_configured(self, send_to_google, send_to_telegram):
        submission = self.create_submission()

        result = deliver_feedback(submission.pk)

        submission.refresh_from_db()
        self.assertEqual(result["status"], "delivered")
        self.assertIsNotNone(submission.google_sent_at)
        self.assertIsNone(submission.telegram_sent_at)
        self.assertIsNotNone(submission.delivered_at)
        send_to_google.assert_called_once()
        send_to_telegram.assert_not_called()

    def test_claimed_submission_is_leased_until_worker_finishes(self):
        submission = self.create_submission()

        claimed_id = claim_next_feedback()

        submission.refresh_from_db()
        self.assertEqual(claimed_id, submission.pk)
        self.assertIsNotNone(submission.next_attempt_at)
        self.assertIsNone(claim_next_feedback())

    @patch("wgapps.tasks._send_to_telegram")
    @patch("wgapps.tasks._send_to_google")
    def test_batch_worker_delivers_due_submission(self, send_to_google, send_to_telegram):
        submission = self.create_submission()

        call_command("process_feedback_queue", "--batch", stdout=StringIO())

        submission.refresh_from_db()
        self.assertIsNotNone(submission.delivered_at)
        send_to_google.assert_called_once()
        send_to_telegram.assert_called_once()

import html
import json
import logging
import urllib.parse
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from wgapps.models import FeedbackSubmission

logger = logging.getLogger(__name__)


class FeedbackDeliveryError(Exception):
    pass


def _request_timeout():
    return max(float(getattr(settings, "FEEDBACK_DELIVERY_TIMEOUT", 10)), 0.1)


def _send_to_google(submission):
    form_id = getattr(settings, "GOOGLE_FORM_ID", "").strip()
    if not form_id:
        raise FeedbackDeliveryError("Google Forms не настроен")

    field_values = (
        ("GOOGLE_ENTRY_NAME", submission.name),
        ("GOOGLE_ENTRY_PHONE", submission.phone),
        ("GOOGLE_ENTRY_MESSAGE", submission.message),
        ("GOOGLE_ENTRY_SOURCE", submission.source),
        ("GOOGLE_ENTRY_CONTACT_METHOD", submission.contact_method),
        ("GOOGLE_ENTRY_TELEGRAM_USERNAME", submission.telegram_username),
    )
    data = {
        entry_name: value
        for setting_name, value in field_values
        if (entry_name := getattr(settings, setting_name, "").strip())
    }
    if not data:
        raise FeedbackDeliveryError("Поля Google Forms не настроены")

    url = f"https://docs.google.com/forms/d/e/{form_id}/formResponse"
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Referer": url},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_request_timeout()):
            pass
    except Exception as exc:
        # Do not persist the full exception: an HTTP error can contain a URL
        # with credentials (notably the Telegram bot token).
        raise FeedbackDeliveryError(
            f"Google Forms: ошибка запроса ({type(exc).__name__})"
        ) from None


def _telegram_is_configured():
    return bool(
        getattr(settings, "TELEGRAM_BOT_TOKEN", "").strip()
        and getattr(settings, "TELEGRAM_CHAT_ID", "").strip()
    )


def _send_to_telegram(submission):
    bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        return

    text = "📩 <b>Новая заявка с сайта</b>"
    if submission.source:
        text += f"\n<b>Раздел:</b> {html.escape(submission.source)}"
    text += (
        f"\n\n<b>Имя:</b> {html.escape(submission.name)}"
        f"\n<b>Телефон:</b> {html.escape(submission.phone)}"
    )
    if submission.contact_method:
        text += f"\n<b>Способы связи:</b> {html.escape(submission.contact_method)}"
        if "Telegram" in submission.contact_method and submission.telegram_username:
            text += f"\n<b>Telegram:</b> {html.escape(submission.telegram_username)}"
    if submission.message:
        text += f"\n<b>Сообщение:</b> {html.escape(submission.message)}"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(
            {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        ).encode(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_request_timeout()) as response:
            result = json.loads(response.read())
    except Exception as exc:
        raise FeedbackDeliveryError(
            f"Telegram: ошибка запроса ({type(exc).__name__})"
        ) from None

    if not result.get("ok"):
        description = str(result.get("description") or "неизвестная ошибка")[:300]
        raise FeedbackDeliveryError(f"Telegram API: {description}")


def _retry_delay(attempt):
    initial = max(int(getattr(settings, "FEEDBACK_RETRY_INITIAL_SECONDS", 60)), 1)
    maximum = max(int(getattr(settings, "FEEDBACK_RETRY_MAX_SECONDS", 3600)), initial)
    return min(initial * (2 ** max(attempt - 1, 0)), maximum)


def claim_next_feedback():
    """Claim one due submission for long enough to perform both HTTP calls."""
    now = timezone.now()
    max_attempts = max(int(getattr(settings, "FEEDBACK_DELIVERY_MAX_ATTEMPTS", 24)), 1)
    lease_seconds = max(int(_request_timeout() * 2) + 60, 60)

    with transaction.atomic():
        submission = (
            FeedbackSubmission.objects.select_for_update(skip_locked=True)
            .filter(delivered_at__isnull=True, attempt_count__lt=max_attempts)
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
            .order_by("created_at")
            .first()
        )
        if submission is None:
            return None

        # If the worker dies, the lease expires and another worker can retry it.
        submission.next_attempt_at = now + timedelta(seconds=lease_seconds)
        submission.save(update_fields=["next_attempt_at"])
        return submission.pk


def deliver_feedback(submission_id):
    submission = FeedbackSubmission.objects.get(pk=submission_id)
    if submission.delivered_at:
        return {"status": "already_delivered", "submission_id": submission_id}

    now = timezone.now()
    submission.attempt_count += 1
    submission.last_attempt_at = now
    submission.save(update_fields=["attempt_count", "last_attempt_at"])

    errors = []

    if not submission.google_sent_at:
        try:
            _send_to_google(submission)
        except FeedbackDeliveryError as exc:
            errors.append(str(exc))
        else:
            submission.google_sent_at = timezone.now()
            submission.save(update_fields=["google_sent_at"])

    telegram_required = _telegram_is_configured()
    if telegram_required and not submission.telegram_sent_at:
        try:
            _send_to_telegram(submission)
        except FeedbackDeliveryError as exc:
            errors.append(str(exc))
        else:
            submission.telegram_sent_at = timezone.now()
            submission.save(update_fields=["telegram_sent_at"])

    if not errors:
        submission.delivered_at = timezone.now()
        submission.last_error = ""
        submission.next_attempt_at = None
        submission.save(update_fields=["delivered_at", "last_error", "next_attempt_at"])
        return {"status": "delivered", "submission_id": submission_id}

    error_text = "; ".join(errors)
    max_attempts = max(int(getattr(settings, "FEEDBACK_DELIVERY_MAX_ATTEMPTS", 24)), 1)
    if submission.attempt_count >= max_attempts:
        submission.last_error = error_text
        submission.next_attempt_at = None
        submission.save(update_fields=["last_error", "next_attempt_at"])
        logger.error(
            "Feedback submission %s was not delivered after %s attempts: %s",
            submission_id,
            submission.attempt_count,
            error_text,
        )
        raise FeedbackDeliveryError(error_text)

    run_after = timezone.now() + timedelta(seconds=_retry_delay(submission.attempt_count))
    submission.last_error = error_text
    submission.next_attempt_at = run_after
    submission.save(update_fields=["last_error", "next_attempt_at"])

    logger.warning(
        "Feedback submission %s delivery failed; retry %s scheduled for %s: %s",
        submission_id,
        submission.attempt_count + 1,
        run_after,
        error_text,
    )
    return {"status": "retry_scheduled", "submission_id": submission_id}

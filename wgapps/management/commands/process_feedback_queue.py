import logging
import math
import time

from django.core.management.base import BaseCommand, CommandError

from wgapps.tasks import FeedbackDeliveryError, claim_next_feedback, deliver_feedback

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Deliver queued feedback submissions to Google Forms and Telegram"

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            default=1.0,
            help="Seconds to wait when there are no due submissions (default: 1)",
        )
        parser.add_argument(
            "--batch",
            action="store_true",
            help="Process all currently due submissions and exit",
        )

    def handle(self, *, interval, batch, **options):
        if not math.isfinite(interval) or interval < 0:
            raise CommandError("--interval must be a finite non-negative number")

        self.stdout.write("Feedback delivery worker started")
        try:
            while True:
                submission_id = claim_next_feedback()
                if submission_id is None:
                    if batch:
                        break
                    time.sleep(interval)
                    continue

                try:
                    deliver_feedback(submission_id)
                except FeedbackDeliveryError:
                    # The delivery function has already saved and logged the
                    # final failure after the configured number of attempts.
                    pass
                except Exception:
                    # The active lease will expire, making the submission due
                    # again even if an unexpected error interrupts processing.
                    logger.exception(
                        "Unexpected error while delivering feedback submission %s",
                        submission_id,
                    )
        except KeyboardInterrupt:
            self.stdout.write("Feedback delivery worker stopped")

from django.db import models


class FeedbackSubmission(models.Model):
    name = models.CharField(max_length=120, verbose_name="Имя")
    phone = models.CharField(max_length=40, verbose_name="Телефон")
    message = models.TextField(max_length=4000, blank=True, verbose_name="Сообщение")
    source = models.CharField(max_length=255, blank=True, verbose_name="Источник")
    contact_method = models.CharField(max_length=255, blank=True, verbose_name="Способы связи")
    telegram_username = models.CharField(max_length=120, blank=True, verbose_name="Telegram")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создана")
    google_sent_at = models.DateTimeField(null=True, blank=True, verbose_name="Отправлена в Google")
    telegram_sent_at = models.DateTimeField(null=True, blank=True, verbose_name="Отправлена в Telegram")
    delivered_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name="Доставлена")
    attempt_count = models.PositiveSmallIntegerField(default=0, verbose_name="Попыток доставки")
    last_attempt_at = models.DateTimeField(null=True, blank=True, verbose_name="Последняя попытка")
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name="Следующая попытка")
    last_error = models.TextField(blank=True, verbose_name="Последняя ошибка")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Заявка"
        verbose_name_plural = "Заявки"

    def __str__(self):
        return f"{self.name} — {self.phone}"

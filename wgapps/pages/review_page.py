from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.models import Page


class ReviewPage(Page):
    author_name = models.CharField(max_length=120, verbose_name="Имя")
    rating = models.PositiveSmallIntegerField(
        verbose_name="Оценка",
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    review_text = models.TextField(max_length=1200, verbose_name="Текст отзыва")

    parent_page_types = ["pages.HomePage"]
    subpage_types = []
    template = "pages/review_page.html"

    content_panels = Page.content_panels + [
        FieldPanel("author_name"),
        FieldPanel("rating"),
        FieldPanel("review_text"),
    ]

    class Meta:
        verbose_name = "Отзыв"
        verbose_name_plural = "Отзывы"

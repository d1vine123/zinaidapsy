from django.db import models
from wagtail.models import Page
from wagtail.fields import StreamField
from wagtail.blocks import StructBlock, CharBlock
from wgapps.blocks.first_block import FirstBlock
from wgapps.blocks.diplomas_block import DiplomaSectionBlock
from wgapps.blocks.feedback import FeedbackBlock
from wgapps.blocks.education_block import EducationBlock
from wgapps.blocks.prices_block import PricesSectionBlock
from wgapps.blocks.video_player_block import VideoPlayerBlock
from wgapps.blocks.about_text_photo_block import AboutTextPhotoBlock
from wagtail.admin.panels import FieldPanel, MultiFieldPanel


class NavLinkBlock(StructBlock):
    text = CharBlock(label="Название пункта")
    anchor = CharBlock(label="Якорь (например: #hero)")

    class Meta:
        label = "Пункт меню"
        icon = "link"


class HomePage(Page):
    # Navigation
    nav_links = StreamField(
        [("link", NavLinkBlock())],
        blank=True,
        verbose_name="Пункты меню",
    )

    # Social links
    telegram_url = models.CharField(max_length=200, blank=True, verbose_name="Telegram URL")
    whatsapp_url = models.CharField(max_length=200, blank=True, verbose_name="WhatsApp URL")
    vk_url = models.CharField(max_length=200, blank=True, verbose_name="ВКонтакте URL")
    max_url = models.CharField(max_length=200, blank=True, verbose_name="MAX URL")

    # Page content
    content = StreamField([
        ("firstblock", FirstBlock()),
        ("about_text_photo", AboutTextPhotoBlock()),
        ("video_player", VideoPlayerBlock()),
        ("education", EducationBlock()),
        ("diplomas", DiplomaSectionBlock()),
        ("prices", PricesSectionBlock()),
        ("feedback", FeedbackBlock()),
    ])

    content_panels = Page.content_panels + [
        MultiFieldPanel([
            FieldPanel("nav_links"),
        ], heading="Навигация"),
        MultiFieldPanel([
            FieldPanel("telegram_url"),
            FieldPanel("whatsapp_url"),
            FieldPanel("vk_url"),
            FieldPanel("max_url"),
        ], heading="Социальные сети"),
        FieldPanel("content"),
    ]

    template = "pages/home_page.html"
    max_count = 1

    class Meta:
        verbose_name = "Главная страница"

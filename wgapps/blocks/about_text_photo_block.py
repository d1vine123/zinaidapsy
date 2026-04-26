from .initialize import *


class AboutTextPhotoBlock(StructBlock):
    anchor_id = CharBlock(
        label="ID раздела (якорь)",
        required=False,
        help_text="Например: about-intro — используется в меню навигации",
    )
    heading = RichTextBlock(label="Заголовок", required=False)
    text = RichTextBlock(
        label="Текст",
        features=["bold", "italic", "link", "ol", "ul"],
        required=False,
    )
    image = ImageChooserBlock(label="Фото", required=False)

    class Meta:
        template = "blocks/about_text_photo_block.html"
        label = "Обо мне: текст + фото"
        icon = "doc-full-inverse"

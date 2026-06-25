from .initialize import *


class FAQBlock(StructBlock):
    anchor_id = CharBlock(
        label="ID раздела (якорь)",
        required=False,
        help_text="Например: faq — используется в меню навигации",
    )
    heading = RichTextBlock(label="Заголовок раздела", required=False)
    description = RichTextBlock(
        label="Вводный текст",
        features=["bold", "italic", "link"],
        required=False,
    )
    items = ListBlock(
        StructBlock([
            ("question", RichTextBlock(label="Вопрос", required=False)),
            ("answer", RichTextBlock(
                label="Ответ",
                features=["bold", "italic", "link", "ul", "ol"],
                required=False,
            )),
        ], label="Вопрос-ответ"),
        label="FAQ",
    )

    class Meta:
        template = "blocks/faq_block.html"
        label = "FAQ"
        icon = "help"

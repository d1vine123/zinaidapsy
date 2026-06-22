from .initialize import *


class ProfessionalTrainingBlock(StructBlock):
    anchor_id = CharBlock(
        label="ID раздела (якорь)",
        required=False,
        help_text="Например: professional-training — используется в меню навигации",
    )
    heading = RichTextBlock(label="Заголовок раздела", required=False)
    description = RichTextBlock(
        label="Вводный текст",
        features=["bold", "italic", "link"],
        required=False,
    )
    items = ListBlock(
        StructBlock([
            ("heading", RichTextBlock(label="Название", required=False)),
            ("description", RichTextBlock(
                label="Описание",
                features=["bold", "italic", "link"],
                required=False,
            )),
        ], label="Пункт подготовки"),
        label="Пункты подготовки",
    )

    class Meta:
        template = "blocks/professional_training_block.html"
        label = "Профессиональная подготовка"
        icon = "form"

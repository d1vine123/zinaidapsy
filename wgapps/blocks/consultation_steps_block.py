from .initialize import *


class ConsultationStepsBlock(StructBlock):
    anchor_id = CharBlock(
        label="ID раздела (якорь)",
        required=False,
        help_text="Например: consultation-steps — используется в меню навигации",
    )
    heading = RichTextBlock(label="Заголовок раздела", required=False)
    description = RichTextBlock(
        label="Вводный текст",
        features=["bold", "italic", "link"],
        required=False,
    )
    steps = ListBlock(
        StructBlock([
            ("heading", RichTextBlock(label="Название шага", required=False)),
            ("description", RichTextBlock(
                label="Описание",
                features=["bold", "italic", "link"],
                required=False,
            )),
        ], label="Шаг"),
        label="Шаги консультации",
    )

    class Meta:
        template = "blocks/consultation_steps_block.html"
        label = "Как проходит консультация"
        icon = "list-ol"

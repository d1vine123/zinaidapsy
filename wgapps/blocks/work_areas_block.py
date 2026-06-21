from .initialize import *


class WorkAreasBlock(StructBlock):
    anchor_id = CharBlock(
        label="ID раздела (якорь)",
        required=False,
        help_text="Например: work-areas — используется в меню навигации",
    )
    heading = RichTextBlock(label="Заголовок раздела", required=False)
    description = RichTextBlock(
        label="Вводный текст",
        features=["bold", "italic", "link"],
        required=False,
    )
    areas = ListBlock(
        StructBlock([
            ("heading", RichTextBlock(label="Название направления", required=False)),
            ("description", RichTextBlock(
                label="Описание",
                features=["bold", "italic", "ul", "ol"],
                required=False,
            )),
        ], label="Направление"),
        label="Направления работы",
    )
    exclusions = RichTextBlock(
        label="С чем не работаю",
        features=["bold", "italic", "ul", "ol"],
        required=False,
    )

    class Meta:
        template = "blocks/work_areas_block.html"
        label = "С чем я работаю"
        icon = "list-ul"

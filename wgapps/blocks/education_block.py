from .initialize import *

class EducationBlock(StructBlock):
    anchor_id = CharBlock(
        label="ID раздела (якорь)",
        required=False,
        help_text="Например: education — используется в меню навигации",
    )
    heading = RichTextBlock(label="Заголовок раздела", required=False)
    education_items = ListBlock(
        StructBlock([
            ("heading", RichTextBlock(label="Заголовок", required=False)),
            ("contents", RichTextBlock(label="Содержимое", required=False)),
        ])
    )

    class Meta:
        template = "blocks/education_block.html"
        label = "Образование и опыт"
        icon = "user"
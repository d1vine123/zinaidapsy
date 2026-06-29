from .initialize import *


class ReviewsBlock(StructBlock):
    anchor_id = CharBlock(
        label="ID раздела (якорь)",
        required=False,
        help_text="Например: reviews — используется в меню навигации",
    )
    heading = CharBlock(label="Заголовок", default="Отзывы")
    button_text = CharBlock(label="Текст кнопки", default="Оставить отзыв")

    def get_context(self, value, parent_context=None):
        context = super().get_context(value, parent_context=parent_context)
        from wgapps.pages.review_page import ReviewPage

        context["reviews"] = (
            ReviewPage.objects.live()
            .public()
            .order_by("-first_published_at", "-latest_revision_created_at")
        )
        context["preview_chars"] = 220
        return context

    class Meta:
        template = "blocks/reviews_block.html"
        label = "Отзывы"
        icon = "pick"

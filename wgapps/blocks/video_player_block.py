from .initialize import *


class VideoPlayerBlock(StructBlock):
    anchor_id = CharBlock(
        label="ID раздела (якорь)",
        required=False,
        help_text="Например: video, practice — используется в меню навигации",
    )
    eyebrow = CharBlock(label="Надзаголовок", required=False)
    heading = CharBlock(label="Заголовок блока")
    description = TextBlock(label="Описание", required=False)
    video_file = DocumentChooserBlock(
        label="Видео-файл",
        required=False,
        help_text="Загрузите mp4/mov/webm как документ, чтобы файл хранился на сервере",
    )
    video_url = CharBlock(
        label="Ссылка на видео",
        required=False,
        help_text="Запасной вариант: /media/videos/session.mp4 или https://example.com/video.mp4",
    )
    poster = ImageChooserBlock(label="Постер", required=False)
    duration_label = CharBlock(
        label="Подпись длительности",
        required=False,
        help_text="Например: 12 минут",
    )
    note = CharBlock(
        label="Подпись под видео",
        required=False,
        help_text="Короткий акцент рядом с видеоплеером",
    )

    class Meta:
        template = "blocks/video_player_block.html"
        label = "Видеопроигрыватель"
        icon = "media"

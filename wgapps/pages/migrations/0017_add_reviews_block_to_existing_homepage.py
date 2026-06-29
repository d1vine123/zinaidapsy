import json
import uuid

from django.db import migrations


def add_reviews_block(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT page_ptr_id, content FROM pages_homepage")
        rows = cursor.fetchall()

    for page_id, raw_content in rows:
        try:
            content = json.loads(raw_content or "[]")
        except (TypeError, ValueError):
            continue

        if any(block.get("type") == "reviews" for block in content):
            continue

        reviews_block = {
            "type": "reviews",
            "value": {
                "anchor_id": "reviews",
                "heading": "Отзывы",
                "button_text": "Оставить отзыв",
            },
            "id": str(uuid.uuid4()),
        }
        insert_at = next(
            (index for index, block in enumerate(content) if block.get("type") == "feedback"),
            len(content),
        )
        content.insert(insert_at, reviews_block)
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE pages_homepage SET content = %s WHERE page_ptr_id = %s",
                [json.dumps(content, ensure_ascii=False), page_id],
            )


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0016_reviewpage_alter_homepage_content"),
    ]

    operations = [
        migrations.RunPython(add_reviews_block, migrations.RunPython.noop),
    ]

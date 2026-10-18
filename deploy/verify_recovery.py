"""Exercise a runtime upgrade using an isolated copy of the site's data.

Run with the candidate environment's Python. Reuse --work-dir between versions
to check successive database migrations. No delivery worker is started.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from importlib.metadata import version
from io import StringIO
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


def prepare_scratch(root, requested):
    """Reject aliases of the source before changing permissions or copying data."""
    scratch = (requested or Path(tempfile.mkdtemp(prefix="zinaidapsy-upgrade-"))).resolve()
    source_database = root / "db.sqlite3"
    database = scratch / "db.sqlite3"
    marker = scratch / ".recovery-check"
    if scratch == root or scratch.is_relative_to((root / "media").resolve()):
        raise SystemExit("Use a separate work directory outside the original media")
    if scratch.exists() and not scratch.is_dir():
        raise SystemExit("The work directory must be a directory")
    if database.is_symlink() or (
        database.exists() and database.samefile(source_database)
    ):
        raise SystemExit("Refusing to use an alias of the original database")
    for name in (".recovery-check", "db.sqlite3-wal", "db.sqlite3-shm", "db.sqlite3-journal", "media", "staticfiles"):
        if (scratch / name).is_symlink():
            raise SystemExit(f"Refusing a symlink in the work directory: {name}")
    if database.exists() and not marker.is_file():
        raise SystemExit("Refusing to migrate an unrecognized database")
    if scratch.exists() and not marker.is_file() and any(scratch.iterdir()):
        raise SystemExit("Use an empty work directory for the initial copy")
    for directory in (scratch / "media", scratch / "staticfiles"):
        if directory.exists() and any(path.is_symlink() for path in directory.rglob("*")):
            raise SystemExit("Refusing symlinks in cloned media or static files")

    scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(scratch, 0o700)
    if not database.exists():
        with sqlite3.connect(source_database.as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(database) as target:
                source.backup(target)
        os.chmod(database, 0o600)
        shutil.copytree(root / "media", scratch / "media", ignore=shutil.ignore_patterns("media", ".DS_Store"))
        marker.touch(mode=0o600)
    return scratch, database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    scratch, database = prepare_scratch(root, args.work_dir)

    sys.path.insert(0, str(root))
    os.environ.update(
        DJANGO_SETTINGS_MODULE="config.settings",
        DB_ENGINE="sqlite",
        DB_NAME=str(database),
        SECRET_KEY="isolated-recovery-verification-only-0123456789abcdefghijklmnopqrstuvwxyz",
        TELEGRAM_BOT_TOKEN="",
        TELEGRAM_CHAT_ID="",
        GOOGLE_FORM_ID="",
        GOOGLE_ENTRY_NAME="",
        GOOGLE_ENTRY_PHONE="",
        GOOGLE_ENTRY_MESSAGE="",
        GOOGLE_ENTRY_SOURCE="",
        GOOGLE_ENTRY_CONTACT_METHOD="",
        GOOGLE_ENTRY_TELEGRAM_USERNAME="",
        PUBLIC_SITE_URL="https://zinaidapsy.ru",
        ALLOWED_HOSTS="zinaidapsy.ru,www.zinaidapsy.ru,testserver",
        DEBUG="False",
        SECURE_SSL_REDIRECT="True",
        SESSION_COOKIE_SECURE="True",
        CSRF_COOKIE_SECURE="True",
        SECURE_HSTS_SECONDS="3600",
    )
    import django
    django.setup()
    from django.test import override_settings

    with override_settings(MEDIA_ROOT=scratch / "media", STATIC_ROOT=scratch / "staticfiles"):
        verify_runtime(scratch, database)


def verify_runtime(scratch, database):
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.test import Client, override_settings
    from PIL import Image
    from wagtail.models import Page, Site
    from wagtail.images import get_image_model
    from wgapps.pages.homepage import HomePage

    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
    assert Path(settings.DATABASES["default"]["NAME"]).resolve() == database.resolve()
    counts_before = (Page.objects.count(), get_image_model().objects.count())
    output = StringIO()
    call_command("migrate", interactive=False, stdout=output)
    assert counts_before == (Page.objects.count(), get_image_model().objects.count()), "Content counts changed"
    site = Site.objects.get(hostname="zinaidapsy.ru")
    Site.objects.exclude(pk=site.pk).update(is_default_site=False)
    site.root_page = HomePage.objects.get()
    site.port = 443
    site.is_default_site = True
    site.save()
    call_command("collectstatic", interactive=False, stdout=output, verbosity=0)
    assert (settings.STATIC_ROOT / "css/output.css").is_file(), "Compiled CSS missing"
    call_command("check", stdout=output)
    client = Client(HTTP_HOST="zinaidapsy.ru")
    routes = ["/", "/robots.txt", "/sitemap.xml", "/admin/login/"]
    routes += [urlsplit(page.get_url()).path for page in Page.objects.live().filter(depth__gt=2)]
    for route in routes:
        response = client.get(route, secure=True)
        assert response.status_code == 200, (route, response.status_code)
        if route == "/":
            assert b"110198201" in response.content, "Metrika counter missing"
        if route == "/sitemap.xml":
            locations = [element.text for element in ET.fromstring(response.content).iter() if element.tag.rsplit("}", 1)[-1] == "loc"]
            assert "https://zinaidapsy.ru/" in locations, "Homepage missing from sitemap"
            assert all(
                urlsplit(location).scheme == "https"
                and urlsplit(location).netloc == "zinaidapsy.ru"
                and not urlsplit(location).query
                and not urlsplit(location).fragment
                for location in locations
            ), "Sitemap contains a noncanonical location"
    administrator = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    assert administrator is not None, "No active administrator in recovery database"
    client.force_login(administrator)
    edit_route = f"/admin/pages/{site.root_page_id}/edit/"
    assert client.get(edit_route, secure=True).status_code == 200, "Wagtail editor failed"
    for image in get_image_model().objects.all():
        assert (settings.MEDIA_ROOT / image.file.name).is_file(), f"Missing original: {image.pk}"
        assert Path(image.file.path).resolve().is_relative_to(settings.MEDIA_ROOT.resolve()), "Original escaped cloned media"
        thumbnail = image.get_rendition("fill-48x48")
        thumbnail_path = Path(thumbnail.file.path).resolve()
        assert thumbnail_path.is_relative_to(settings.MEDIA_ROOT.resolve()), "Thumbnail escaped cloned media"
        with Image.open(thumbnail_path) as generated:
            assert generated.size == (48, 48), f"Thumbnail generation failed: {image.pk}"
    with sqlite3.connect(database) as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    # The existing unit tests use HTTP requests; HTTPS was exercised above.
    with override_settings(SECURE_SSL_REDIRECT=False):
        call_command("test", "wgapps", interactive=False, verbosity=0, stdout=output)
    print(json.dumps({
        "Django": version("Django"), "Wagtail": version("wagtail"),
        "pages": counts_before[0], "images": counts_before[1],
        "thumbnails": counts_before[1],
        "routes": routes, "checks": "passed", "work_dir": str(scratch),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

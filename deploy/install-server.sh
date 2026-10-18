#!/usr/bin/env bash
# First installation only. Run on the VPS, never on the source computer.
set -Eeuo pipefail
umask 027

readonly BASE=/srv/zinaidapsy
readonly APP=$BASE/app
readonly PRIVATE=$BASE/private
readonly SHARED=$BASE/shared
readonly VENV=$BASE/venv
readonly SITE=/etc/nginx/sites-available/zinaidapsy
stage=preflight

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
failed() {
    local result=$?
    printf '\nInstallation stopped during %s (line %s). No worker was started.\n' "$stage" "$1" >&2
    printf 'Inspect the failure before continuing; this first-install script refuses an existing runtime.\n' >&2
    exit "$result"
}
trap 'failed "$LINENO"' ERR

[[ $# -eq 1 ]] || die "Usage: sudo bash $APP/deploy/install-server.sh /absolute/path/to/zinaidapsy-data"
[[ $EUID -eq 0 ]] || die 'Run this script as root or with sudo.'
[[ -f /etc/os-release ]] || die 'Ubuntu 24.04 is required.'
# This is the operating system's root-owned identification file, not user input.
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || die 'This installer supports Ubuntu 24.04 only.'
for program in realpath python3 git systemctl getent runuser; do
    command -v "$program" >/dev/null || die "Required preflight command is missing: $program"
done

DATA=$(realpath -e -- "$1")
readonly DATA
[[ -d $DATA && $DATA != / ]] || die 'The data argument must name a directory.'
[[ $DATA == "$(realpath -ms -- "$1")" ]] || die 'The data directory path must not traverse symlinks.'
[[ $DATA != "$BASE" && $DATA != "$BASE/"* ]] || die 'Keep the incoming data outside /srv/zinaidapsy.'
[[ -d $APP/.git && ! -L $APP/.git ]] || die 'Clone the repository into /srv/zinaidapsy/app first.'
[[ $(realpath -e -- "$APP") == "$APP" ]] || die 'The application path must not traverse symlinks.'
[[ $(git -C "$APP" rev-parse --show-toplevel) == "$APP" ]] || die 'Unexpected Git checkout root.'
[[ -z $(git -C "$APP" status --porcelain --untracked-files=all) ]] || die 'The server checkout must be clean.'
[[ -z $(git -C "$APP" ls-files -- media zinaidapsy.git 'db.sqlite3*' .env) ]] || die 'Publish the cleaned Git commit first: media, database backups and nested Git archives must not be tracked.'
[[ -z $(find "$APP" -type l -print -quit) ]] || die 'Unexpected symlink inside the fresh checkout.'
[[ -z $(find "$DATA" -type l -print -quit) ]] || die 'Incoming data must not contain symlinks.'

for path in "$PRIVATE" "$SHARED" "$VENV" "$APP/.env" "$APP/media" "$APP/staticfiles" "$APP/db.sqlite3" /run/zinaidapsy-web.sock "$SITE" /etc/nginx/sites-enabled/zinaidapsy; do
    [[ ! -e $path && ! -L $path ]] || die "Refusing an existing installation path: $path"
done
for unit in zinaidapsy-web.socket zinaidapsy-web.service zinaidapsy-feedback.service; do
    for directory in /etc/systemd/system /run/systemd/system /run/systemd/transient /usr/lib/systemd/system; do
        [[ ! -e $directory/$unit && ! -L $directory/$unit && ! -e $directory/$unit.d ]] || die "Existing systemd configuration: $unit"
    done
    if systemctl is-active --quiet "$unit"; then
        die "An application unit is already running: $unit"
    fi
done
! getent passwd zinaidapsy >/dev/null || die 'The dedicated zinaidapsy account already exists; review the existing installation.'
! getent group zinaidapsy >/dev/null || die 'The dedicated zinaidapsy group already exists; review the existing installation.'
shopt -s nullglob
for path in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
    [[ $path == /etc/nginx/sites-enabled/default && -L $path && $(realpath -e -- "$path") == /etc/nginx/sites-available/default ]] || die "Existing nginx site needs manual review: $path"
done
shopt -u nullglob
for name in manage.py config/settings.py static/css/output.css deploy/requirements-production.txt deploy/zinaidapsy-web.socket deploy/zinaidapsy-web.service deploy/zinaidapsy-feedback.service deploy/nginx-http.conf deploy/nginx.conf deploy/certbot-renew-nginx.sh; do
    [[ -f $APP/$name && ! -L $APP/$name ]] || die "Required repository file is missing: $name"
done
for name in db.sqlite3 production.env; do
    [[ -f $DATA/$name && ! -L $DATA/$name ]] || die "Required incoming file is missing: $name"
done
[[ -d $DATA/media ]] || die 'The incoming media directory is missing.'
for suffix in -wal -shm -journal; do
    [[ ! -e $DATA/db.sqlite3$suffix ]] || die 'Supply a standalone SQLite backup made with the backup API, without journal/WAL files.'
done

# Validate values without sourcing or echoing secrets. Python is part of Ubuntu's base system.
python3 - "$DATA" <<'PY'
from pathlib import Path
import re, shlex, sqlite3, stat, sys

data = Path(sys.argv[1])
env_file = data / 'production.env'
if stat.S_IMODE(env_file.stat().st_mode) & 0o077:
    raise SystemExit('production.env must be private: chmod 600 the incoming file')
allowed = set('SECRET_KEY DEBUG ALLOWED_HOSTS CSRF_TRUSTED_ORIGINS SECURE_SSL_REDIRECT SESSION_COOKIE_SECURE CSRF_COOKIE_SECURE SECURE_HSTS_SECONDS SECURE_HSTS_INCLUDE_SUBDOMAINS SECURE_HSTS_PRELOAD WAGTAIL_SITE_NAME WAGTAILADMIN_BASE_URL PUBLIC_SITE_URL DB_ENGINE DB_NAME TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID GOOGLE_FORM_ID GOOGLE_ENTRY_NAME GOOGLE_ENTRY_PHONE GOOGLE_ENTRY_MESSAGE GOOGLE_ENTRY_SOURCE GOOGLE_ENTRY_CONTACT_METHOD GOOGLE_ENTRY_TELEGRAM_USERNAME FEEDBACK_DELIVERY_TIMEOUT FEEDBACK_DELIVERY_MAX_ATTEMPTS FEEDBACK_RETRY_INITIAL_SECONDS FEEDBACK_RETRY_MAX_SECONDS'.split())
values = {}
for number, raw in enumerate(env_file.read_text().splitlines(), 1):
    line = raw.strip()
    if not line or line.startswith('#'):
        continue
    key, separator, value = line.partition('=')
    if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key) or key not in allowed or key in values:
        raise SystemExit(f'Invalid or duplicate environment key on line {number}')
    if '${' in value or '\\' in value:
        raise SystemExit(f'Use literal values without interpolation or escapes on line {number}')
    if value.startswith(('"', "'")):
        try:
            parts = shlex.split(value, comments=False)
        except ValueError:
            raise SystemExit(f'Invalid environment quoting on line {number}') from None
        if len(parts) != 1:
            raise SystemExit(f'Invalid environment value on line {number}')
        value = parts[0]
    elif any(character.isspace() for character in value):
        raise SystemExit(f'Quote environment values containing spaces on line {number}')
    values[key] = value
expected = {
    'DB_ENGINE': 'sqlite', 'DB_NAME': '/srv/zinaidapsy/private/db.sqlite3',
    'PUBLIC_SITE_URL': 'https://zinaidapsy.ru',
    'WAGTAILADMIN_BASE_URL': 'https://zinaidapsy.ru',
}
for key, value in expected.items():
    if values.get(key) != value:
        raise SystemExit(f'Unexpected production setting: {key}')
if values.get('DEBUG', '').lower() not in {'false', '0', 'off', 'no'}:
    raise SystemExit('DEBUG must be False')
for key in ('SECURE_SSL_REDIRECT', 'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE'):
    if values.get(key, '').lower() not in {'true', '1', 'on', 'yes'}:
        raise SystemExit(f'{key} must be True')
if set(values.get('ALLOWED_HOSTS', '').split(',')) != {'zinaidapsy.ru', 'www.zinaidapsy.ru'}:
    raise SystemExit('ALLOWED_HOSTS must contain only zinaidapsy.ru,www.zinaidapsy.ru')
if set(values.get('CSRF_TRUSTED_ORIGINS', '').split(',')) != {'https://zinaidapsy.ru', 'https://www.zinaidapsy.ru'}:
    raise SystemExit('CSRF_TRUSTED_ORIGINS must contain both HTTPS domain names')
secret = values.get('SECRET_KEY', '')
if len(secret) < 50 or len(set(secret)) < 8 or secret.upper().startswith(('REPLACE', 'CHANGE', 'TEST')):
    raise SystemExit('Supply a newly generated random SECRET_KEY of at least 50 characters')
database = data / 'db.sqlite3'
with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
    if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        raise SystemExit('SQLite integrity check failed')
    if connection.execute('PRAGMA foreign_key_check').fetchall():
        raise SystemExit('SQLite foreign key check failed')
    if connection.execute('SELECT COUNT(*) FROM pages_homepage').fetchone()[0] != 1:
        raise SystemExit('The supplied database must contain exactly one homepage')
    media = (data / 'media').resolve()
    for table in ('wagtailimages_image', 'wagtailimages_rendition', 'wagtaildocs_document'):
        for (name,) in connection.execute(f'SELECT file FROM {table}'):
            candidate = (media / name).resolve()
            if not candidate.is_relative_to(media) or not candidate.is_file():
                raise SystemExit(f'Missing or unsafe media referenced by {table}; repair the incoming package')
print('Preflight passed: production settings, SQLite and referenced media verified.')
PY

stage='system packages'
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3.12 python3.12-venv python3.12-dev git nginx certbot build-essential curl rsync
getent group www-data >/dev/null || die 'nginx must provide the www-data group.'
stage='directories and protected data'
useradd --system --user-group --home-dir "$BASE" --shell /usr/sbin/nologin zinaidapsy
install -d -o root -g root -m 0755 "$BASE"
# Root retains Git credentials and writes code. Services receive read access only.
chown -R root:zinaidapsy "$APP"
find "$APP" -path "$APP/.git" -prune -o -type d -exec chmod 2750 {} +
find "$APP" -path "$APP/.git" -prune -o -type f -exec chmod 0640 {} +
chown -R root:root "$APP/.git"
find "$APP/.git" -type d -exec chmod 0700 {} +
find "$APP/.git" -type f -exec chmod 0600 {} +
install -d -o zinaidapsy -g zinaidapsy -m 0700 "$PRIVATE"
install -d -o zinaidapsy -g www-data -m 2750 "$SHARED" "$SHARED/media" "$SHARED/staticfiles"
install -d -o zinaidapsy -g zinaidapsy -m 0750 "$VENV"
install -o zinaidapsy -g zinaidapsy -m 0600 "$DATA/production.env" "$PRIVATE/production.env"
install -o zinaidapsy -g zinaidapsy -m 0600 "$DATA/db.sqlite3" "$PRIVATE/db.sqlite3"
install -o zinaidapsy -g zinaidapsy -m 0600 "$DATA/db.sqlite3" "$PRIVATE/db.sqlite3.before-migrate"
rsync -a --chown=zinaidapsy:www-data "$DATA/media/" "$SHARED/media/"
find "$SHARED/media" -type d -exec chmod 2750 {} +
find "$SHARED/media" -type f -exec chmod 0640 {} +
ln -s "$PRIVATE/production.env" "$APP/.env"
ln -s "$SHARED/media" "$APP/media"
ln -s "$SHARED/staticfiles" "$APP/staticfiles"

app_python() {
    runuser -u zinaidapsy -g www-data -G zinaidapsy -- env -i \
        PATH=/usr/bin:/bin HOME="$BASE" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
        "$VENV/bin/python" "$@"
}
stage='isolated Python runtime'
runuser -u zinaidapsy -- python3.12 -m venv "$VENV"
app_python -m pip install --no-cache-dir -r "$APP/deploy/requirements-production.txt"
app_python -m pip check
stage='database migrations and static files'
cd "$APP"
app_python manage.py migrate --plan
app_python manage.py migrate --noinput
app_python manage.py shell <<'PY'
from django.db import transaction
from wagtail.models import Site
from wgapps.pages.homepage import HomePage
with transaction.atomic():
    home = HomePage.objects.get()
    site, _ = Site.objects.get_or_create(hostname='zinaidapsy.ru', defaults={'root_page': home})
    Site.objects.exclude(pk=site.pk).update(is_default_site=False)
    site.root_page = home
    site.port = 443
    site.is_default_site = True
    site.save()
PY
app_python manage.py collectstatic --noinput
find "$SHARED/staticfiles" -type d -exec chmod 2750 {} +
find "$SHARED/staticfiles" -type f -exec chmod 0640 {} +
app_python manage.py check --deploy

stage='systemd and private web verification'
for unit in zinaidapsy-web.socket zinaidapsy-web.service zinaidapsy-feedback.service; do
    install -o root -g root -m 0644 "$APP/deploy/$unit" /etc/systemd/system/
done
for unit in zinaidapsy-web.service zinaidapsy-feedback.service; do
    install -d -o root -g root -m 0755 "/etc/systemd/system/$unit.d"
    printf '[Service]\nSupplementaryGroups=zinaidapsy\n' >"/etc/systemd/system/$unit.d/10-code-read-access.conf"
    chmod 0644 "/etc/systemd/system/$unit.d/10-code-read-access.conf"
done
# Gunicorn 26's optional control socket would otherwise try the read-only home.
printf '[Service]\nEnvironment="GUNICORN_CMD_ARGS=--no-control-socket"\n' >/etc/systemd/system/zinaidapsy-web.service.d/20-no-control-socket.conf
chmod 0644 /etc/systemd/system/zinaidapsy-web.service.d/20-no-control-socket.conf
systemd-analyze verify /etc/systemd/system/zinaidapsy-web.socket /etc/systemd/system/zinaidapsy-web.service /etc/systemd/system/zinaidapsy-feedback.service
systemctl daemon-reload
systemctl enable --now zinaidapsy-web.socket zinaidapsy-web.service
runuser -u www-data -- curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 1 \
    --unix-socket /run/zinaidapsy-web.sock -o /dev/null \
    -H 'Host: zinaidapsy.ru' -H 'X-Forwarded-Proto: https' http://localhost/
runuser -u www-data -- test -r "$SHARED/staticfiles/css/output.css"
runuser -u www-data -- test ! -r "$PRIVATE/db.sqlite3"
runuser -u www-data -- test ! -r "$PRIVATE/production.env"

stage='temporary HTTP ACME configuration'
install -d -o root -g root -m 0755 /var/www/letsencrypt/.well-known/acme-challenge
install -o root -g root -m 0644 "$APP/deploy/nginx-http.conf" "$SITE"
ln -s "$SITE" /etc/nginx/sites-enabled/zinaidapsy
if [[ -L /etc/nginx/sites-enabled/default ]]; then
    unlink /etc/nginx/sites-enabled/default
fi
nginx -t
systemctl enable --now nginx.service
systemctl reload nginx.service

cat <<'NEXT'

Installation prepared. The web service passed a private Unix-socket request.
Public HTTP returns 503 until HTTPS is configured. The feedback worker is STOPPED.

Next, point zinaidapsy.ru and www to this VPS; preserve MX/TXT records and remove
stale AAAA records unless this VPS has working IPv6. Open TCP 80/443 in the VPS
firewall/provider panel, preserving SSH access. No firewall was enabled here.

Then run in an interactive SSH session, replacing YOUR_EMAIL:
  sudo bash /srv/zinaidapsy/app/deploy/enable-https.sh YOUR_EMAIL
This checks public DNS/HTTP, asks you to accept the certificate terms,
installs HTTPS and its renewal hook, and verifies the public endpoints.

Check images, the Wagtail admin, HTTPS redirects and Metrika 110198201.
Only after reviewing the delivery settings and saved queue, explicitly start:
  systemctl enable --now zinaidapsy-feedback.service
This last command sends queued submissions to real Google Forms/Telegram.

Future Git pulls run as root with umask 027; code remains root-owned.
Keep the incoming private data package protected until off-server backups exist.
NEXT

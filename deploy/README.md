# Восстановление на VPS

Для установки кода через Git используйте [GIT-DEPLOY.md](GIT-DEPLOY.md):
команды публикации, отдельный перенос данных и скрипты установки/HTTPS.
Ниже сохранён вариант ручного переноса файлов.

Сценарий первой установки на отдельный VPS с Ubuntu 24.04 и Python 3.12.
Нужны SSH с sudo, публичный IP, входящие TCP 22/80/443 и возможность менять DNS.
Обычный виртуальный хостинг REG нельзя считать подходящим без проверки поддержки
Python 3.12, WSGI и постоянного фонового процесса. Эти файлы ещё не применялись
на сервере; создание VPS, смена DNS и запуск сервисов выполняются отдельно.

Для нового сервера используйте `deploy/requirements-production.txt`: проверенное
окружение Python 3.12 с Django 5.2.18 и Wagtail 7.4.3 LTS. Прямые зависимости
перечислены в `requirements-production.in`, полный список закреплён в `.txt`.
Старый корневой `requirements.txt` сохранён; он содержит неподдерживаемый Django
5.1 и множество библиотек, не используемых сайтом.

На отдельной копии БД проверены переходы Wagtail 7.0.9 → 7.1.3 → 7.2.3 →
7.3.4 → 7.4.3, миграции, опубликованные страницы, редактор, изображения,
robots/sitemap и все 9 тестов заявок. Это проверка на macOS; установку и сервисы
на целевом Ubuntu нужно проверить отдельно. Скрипт `deploy/verify_recovery.py`
проверяет выбранное окружение на изолированной копии данных, не запуская доставку.
Основа обновления: [поддерживаемые Django](https://www.djangoproject.com/download/)
и [порядок обновления Wagtail](https://docs.wagtail.org/en/stable/releases/upgrading.html).

## 1. Подготовить перенос на своём компьютере

Сначала сравните местную копию с резервными копиями прежнего сервера. Основная
местная `db.sqlite3` содержит отзывы, а `data_dump.json` их ещё не содержит.
Работайте из корня проекта. Команды создают отдельный пакет; исходники не меняют.
Не копируйте поверх уже работающего сервера его БД или media.

```bash
RECOVERY_DIR=$(mktemp -d "${TMPDIR:-/tmp}/zinaidapsy-transfer.XXXXXX")
chmod 700 "$RECOVERY_DIR"
rsync -a --exclude='.git/' --exclude='zinaidapsy.git/' \
  --exclude='.env*' --exclude='venv/' --exclude='node_modules/' \
  --exclude='media/' --exclude='staticfiles/' --exclude='recovery/' \
  --exclude='db.sqlite3*' --exclude='data_dump.json' \
  --exclude='__pycache__/' --exclude='.DS_Store' ./ "$RECOVERY_DIR/app/"
mkdir -p "$RECOVERY_DIR/media/original_images"
rsync -a --exclude='media/' --exclude='.DS_Store' media/ "$RECOVERY_DIR/media/"
rsync -a --ignore-existing original_images/ "$RECOVERY_DIR/media/original_images/"
python3 - "$RECOVERY_DIR/db.sqlite3" <<'PY'
import sqlite3, sys
with sqlite3.connect('file:db.sqlite3?mode=ro', uri=True) as source:
    with sqlite3.connect(sys.argv[1]) as target:
        source.backup(target)
        assert target.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
print('SQLite backup verified')
PY
VPS=ssh_user@VPS_IP
rsync -av --dry-run "$RECOVERY_DIR/" "$VPS:recovery-incoming/"
rsync -av "$RECOVERY_DIR/" "$VPS:recovery-incoming/"
```

SQLite backup API получает согласованную копию, включая данные WAL. Для согласования
БД с media на время снимка остановите локальное редактирование. Секретный `.env`,
виртуальное окружение и дублирующий `media/media/` в пакет не входят. Четыре старых
оригинала добавляются из `original_images/`, существующие файлы сохраняются.
Перед rsync проверьте SSH fingerprint VPS по данным провайдера.

## 2. Подготовить новый сервер

Далее команды выполняются **на VPS**, из обычной SSH-сессии с sudo. Подставьте
реальный IP при подключении. Сценарий рассчитан на пустой `/srv/zinaidapsy`.

```bash
set -eu
sudo apt update
sudo apt install -y python3.12-venv python3.12-dev build-essential libpq-dev nginx certbot rsync
sudo useradd --system --user-group --home-dir /srv/zinaidapsy --shell /usr/sbin/nologin zinaidapsy
sudo install -d -m 0755 /srv/zinaidapsy
sudo install -d -o zinaidapsy -g zinaidapsy -m 0750 /srv/zinaidapsy/app
sudo install -d -o zinaidapsy -g zinaidapsy -m 0700 /srv/zinaidapsy/private
sudo install -d -o zinaidapsy -g www-data -m 2750 /srv/zinaidapsy/shared
sudo install -d -o zinaidapsy -g www-data -m 2750 /srv/zinaidapsy/shared/media /srv/zinaidapsy/shared/staticfiles
sudo rsync -a --chown=zinaidapsy:zinaidapsy ~/recovery-incoming/app/ /srv/zinaidapsy/app/
sudo find /srv/zinaidapsy/app -type d -exec chmod 0750 {} +
sudo find /srv/zinaidapsy/app -type f -exec chmod 0640 {} +
sudo test ! -e /srv/zinaidapsy/private/db.sqlite3
sudo install -o zinaidapsy -g zinaidapsy -m 0600 ~/recovery-incoming/db.sqlite3 /srv/zinaidapsy/private/db.sqlite3
sudo rsync -a --chown=zinaidapsy:www-data ~/recovery-incoming/media/ /srv/zinaidapsy/shared/media/
sudo find /srv/zinaidapsy/shared/media -type d -exec chmod 2750 {} +
sudo find /srv/zinaidapsy/shared/media -type f -exec chmod 0640 {} +
sudo ln -s /srv/zinaidapsy/shared/media /srv/zinaidapsy/app/media
sudo ln -s /srv/zinaidapsy/shared/staticfiles /srv/zinaidapsy/app/staticfiles
sudo install -o zinaidapsy -g zinaidapsy -m 0600 /srv/zinaidapsy/app/deploy/production.env.example /srv/zinaidapsy/private/production.env
sudo ln -s /srv/zinaidapsy/private/production.env /srv/zinaidapsy/app/.env
sudo install -d -o zinaidapsy -g zinaidapsy -m 0750 /srv/zinaidapsy/venv
sudo -u zinaidapsy python3.12 -m venv /srv/zinaidapsy/venv
sudo -u zinaidapsy /srv/zinaidapsy/venv/bin/python -m pip install -r /srv/zinaidapsy/app/deploy/requirements-production.txt
sudo -u zinaidapsy /srv/zinaidapsy/venv/bin/python -m pip check
```

Отредактируйте приватный файл: `sudo -u zinaidapsy nano /srv/zinaidapsy/private/production.env`.
Замените SECRET_KEY; новое значение можно создать командой
`python3 -c 'import secrets; print(secrets.token_urlsafe(64))'`.
Перенесите из сохранённого местного `.env` только Telegram/Google Forms переменные
через защищённую SSH-сессию. Не публикуйте их в чате или репозитории. Не переносите
местные DEBUG/HTTPS настройки. Секреты в примере пустые; Google Forms обязателен
для штатной доставки заявок, Telegram можно оставить выключенным.

## 3. Подготовить БД и проверить приложение

Команды manage.py читают тот же production.env через защищённую ссылку `.env`.
Ничего не отправляйте в очередь во время проверки. Воркера пока не запускайте.

```bash
sudo -u zinaidapsy cp -p /srv/zinaidapsy/private/db.sqlite3 /srv/zinaidapsy/private/db.sqlite3.before-migrate
sudo -u zinaidapsy /srv/zinaidapsy/venv/bin/python /srv/zinaidapsy/app/manage.py migrate --plan
sudo -u zinaidapsy /srv/zinaidapsy/venv/bin/python /srv/zinaidapsy/app/manage.py migrate --noinput
sudo -u zinaidapsy -g www-data /srv/zinaidapsy/venv/bin/python /srv/zinaidapsy/app/manage.py collectstatic --noinput
sudo -u zinaidapsy /srv/zinaidapsy/venv/bin/python /srv/zinaidapsy/app/manage.py check --deploy
sudo -u zinaidapsy /srv/zinaidapsy/venv/bin/python /srv/zinaidapsy/app/manage.py shell <<'PY'
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
sudo install -m 0644 /srv/zinaidapsy/app/deploy/zinaidapsy-web.socket /etc/systemd/system/
sudo install -m 0644 /srv/zinaidapsy/app/deploy/zinaidapsy-web.service /etc/systemd/system/
sudo install -m 0644 /srv/zinaidapsy/app/deploy/zinaidapsy-feedback.service /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/zinaidapsy-web.socket /etc/systemd/system/zinaidapsy-web.service /etc/systemd/system/zinaidapsy-feedback.service
sudo systemctl daemon-reload
sudo systemctl enable --now zinaidapsy-web.socket zinaidapsy-web.service
sudo -u www-data curl --fail --unix-socket /run/zinaidapsy-web.sock -I -H 'Host: zinaidapsy.ru' -H 'X-Forwarded-Proto: https' http://localhost/
sudo -u www-data test -r /srv/zinaidapsy/shared/staticfiles/css/output.css
sudo -u www-data test ! -r /srv/zinaidapsy/private/db.sqlite3
sudo -u www-data test ! -r /srv/zinaidapsy/private/production.env
```

Проверьте результат `check --deploy` и снимок главной до переключения DNS.
`/srv/zinaidapsy/private` закрыт от nginx; ему доступны только media/static
и сокет. Код не является nginx document root. systemd разрешает веб-процессу
записывать БД и media, воркеру — только приватные данные. Не делайте `chmod -R 777`.

## 4. DNS и сертификат

Переходите к публичному запуску после установки проверенного production-окружения
и проверки приложения на новом сервере.

Сохраните прежнюю DNS-зону. Для `@` задайте A нового VPS, `www` — CNAME на
`zinaidapsy.ru.` либо тот же A. AAAA должна указывать на рабочий IPv6 VPS;
не оставляйте AAAA старого сервера. MX/TXT и почтовые записи сохраняются.
Проверьте A/AAAA и доступность портов 80/443 извне. Для нового VPS можно применить
`sudo ufw allow OpenSSH`, `sudo ufw allow 'Nginx Full'`, затем включить firewall;
до включения убедитесь, что правило SSH соответствует вашему порту.

Сначала временная HTTP-конфигурация позволяет получить сертификат и отвечает 503
на остальные запросы. В стандартной установке Ubuntu уберите ссылку default,
чтобы не получить конфликт `default_server`:

```bash
sudo install -d -m 0755 /var/www/letsencrypt/.well-known/acme-challenge
if [ -L /etc/nginx/sites-enabled/default ]; then sudo unlink /etc/nginx/sites-enabled/default; fi
sudo install -m 0644 /srv/zinaidapsy/app/deploy/nginx-http.conf /etc/nginx/sites-available/zinaidapsy
sudo ln -s /etc/nginx/sites-available/zinaidapsy /etc/nginx/sites-enabled/zinaidapsy
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/letsencrypt --cert-name zinaidapsy.ru -d zinaidapsy.ru -d www.zinaidapsy.ru
sudo install -m 0644 /srv/zinaidapsy/app/deploy/nginx.conf /etc/nginx/sites-available/zinaidapsy
sudo nginx -t
sudo systemctl reload nginx
sudo install -m 0755 /srv/zinaidapsy/app/deploy/certbot-renew-nginx.sh /etc/letsencrypt/renewal-hooks/deploy/zinaidapsy-nginx
sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run
```

Проверка nginx обязательна **перед каждым reload**. Не применяйте HTTPS-шаблон,
пока оба файла сертификата не созданы. При существующем другом nginx-сайте
сначала согласуйте конфигурацию; не заменяйте чужие server blocks.

## 5. Проверить сайт и включить доставку

```bash
curl --fail -I https://zinaidapsy.ru/
curl -I http://zinaidapsy.ru/
curl -I https://www.zinaidapsy.ru/
curl --fail https://zinaidapsy.ru/robots.txt
curl --fail https://zinaidapsy.ru/sitemap.xml
curl --fail -I https://zinaidapsy.ru/static/css/output.css
curl -I https://zinaidapsy.ru/.env
curl -I https://zinaidapsy.ru/db.sqlite3
sudo systemctl status zinaidapsy-web nginx --no-pager
sudo journalctl -u zinaidapsy-web -n 50 --no-pager
```

Ожидаются 200 для сайта/robots/sitemap/CSS, редирект HTTP и www на
`https://zinaidapsy.ru`, 404 для `.env` и БД, корректный сертификат без `curl -k`.
В браузере проверьте мобильный вид, все изображения, согласие и `/admin/`.

После проверки реквизитов включите **один** воркер. Следующая команда начнёт
отправлять сохранённые заявки в реальные Google Forms и Telegram:

```bash
sudo systemctl enable --now zinaidapsy-feedback.service
sudo systemctl status zinaidapsy-feedback --no-pager
```

Отправьте одну явно помеченную тестовую заявку через HTTPS, подтвердите доставку
и отсутствие дублей. Проверьте счётчик Метрики **110198201**, цели и последние
визиты; в Яндекс Вебмастере — главное зеркало, sitemap, ошибки и переобход главной.
Возвращение поисковых позиций требует повторного обхода и не гарантируется сразу.

Для отката остановите веб-сервис, сокет и воркер **до** восстановления резервной
БД; не затирайте новые заявки. Резервируйте SQLite через backup API и media,
храните копию отдельно от VPS. Пакет `recovery-incoming` содержит персональные
данные: после проверки перенесите его в защищённый архив либо удалите вручную.

Основа конфигурации: [Gunicorn/systemd](https://gunicorn.org/deploy/),
[nginx proxy](https://nginx.org/en/docs/http/ngx_http_proxy_module.html),
[Django deployment checklist](https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/),
[systemd permissions](https://www.freedesktop.org/software/systemd/man/255/systemd.exec.html),
[Certbot webroot и renewal](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot).

#!/usr/bin/env bash
# Run on the prepared VPS after both domain names point at this server.
set -euo pipefail
umask 077

die() {
    printf 'Ошибка: %s\n' "$*" >&2
    exit 1
}

if [[ $# -ne 1 ]]; then
    printf 'Использование: sudo bash %s EMAIL\n' "$0" >&2
    exit 2
fi
EMAIL=$1
[[ $EMAIL =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ && $EMAIL != -* ]] \
    || die 'Укажите действующий email для уведомлений Let’s Encrypt.'

if [[ $EUID -ne 0 ]]; then
    exec sudo -- bash -- "$0" "$@"
fi
[[ -t 0 ]] || die 'Запустите скрипт в интерактивной SSH-сессии: Certbot предложит принять условия Let’s Encrypt.'

DOMAIN=zinaidapsy.ru
DEPLOY_DIR=/srv/zinaidapsy/app/deploy
WEBROOT=/var/www/letsencrypt
ACME_DIR=$WEBROOT/.well-known/acme-challenge
SITE_AVAILABLE=/etc/nginx/sites-available/zinaidapsy
SITE_ENABLED=/etc/nginx/sites-enabled/zinaidapsy
CERT_DIR=/etc/letsencrypt/live/$DOMAIN
PROBE_FILE=
NGINX_BACKUP=

cleanup() {
    local result=$?
    trap - EXIT
    if [[ -n $NGINX_BACKUP ]]; then
        printf 'Возвращаю предыдущую конфигурацию nginx.\n' >&2
        if cp -p -- "$NGINX_BACKUP" "$SITE_AVAILABLE"; then
            if nginx -t; then
                systemctl reload nginx.service || true
            fi
        else
            printf 'Резервная конфигурация сохранена: %s\n' "$NGINX_BACKUP" >&2
            exit "$result"
        fi
        rm -f -- "$NGINX_BACKUP"
    fi
    if [[ -n $PROBE_FILE ]]; then
        rm -f -- "$PROBE_FILE"
    fi
    exit "$result"
}
trap cleanup EXIT

for executable in certbot nginx systemctl curl cmp readlink install mktemp cp rm; do
    command -v "$executable" >/dev/null || die "Не найдена команда $executable; сначала выполните install-server.sh."
done
for template in nginx-http.conf nginx.conf certbot-renew-nginx.sh; do
    [[ -r $DEPLOY_DIR/$template ]] || die "Не найден $DEPLOY_DIR/$template."
done
[[ -f $SITE_AVAILABLE && ! -L $SITE_AVAILABLE ]] || die 'Не найден отдельный управляемый конфиг nginx; сначала выполните install-server.sh.'
[[ -L $SITE_ENABLED ]] || die 'Сайт не включён в nginx; сначала выполните install-server.sh.'
[[ $(readlink -f -- "$SITE_ENABLED") == "$SITE_AVAILABLE" ]] || die 'Ссылка сайта nginx указывает на другой файл.'
if ! cmp -s -- "$SITE_AVAILABLE" "$DEPLOY_DIR/nginx-http.conf" \
    && ! cmp -s -- "$SITE_AVAILABLE" "$DEPLOY_DIR/nginx.conf"; then
    die 'Конфигурация nginx отличается от шаблонов проекта. Проверьте изменения перед заменой.'
fi
nginx -t
systemctl is-active --quiet nginx.service || die 'nginx не запущен.'
systemctl is-active --quiet zinaidapsy-web.service || die 'Веб-сервис не запущен; проверьте install-server.sh и journalctl.'

# Verify that public DNS and HTTP for both names reach this webroot before ACME.
install -d -m 0755 "$ACME_DIR"
PROBE_FILE=$(mktemp "$ACME_DIR/zinaidapsy-check.XXXXXXXX")
PROBE_NAME=${PROBE_FILE##*/}
printf '%s' "$PROBE_NAME" > "$PROBE_FILE"
chmod 0644 "$PROBE_FILE"
for host in "$DOMAIN" "www.$DOMAIN"; do
    response=$(curl --silent --show-error --fail --noproxy '*' \
        --connect-timeout 10 --max-time 30 \
        "http://$host/.well-known/acme-challenge/$PROBE_NAME") \
        || die "HTTP-проверка $host не прошла. Проверьте A/AAAA, порт 80 и повторите запуск."
    [[ $response == "$PROBE_NAME" ]] \
        || die "$host отвечает с другого сайта. Проверьте DNS перед выпуском сертификата."
done
rm -f -- "$PROBE_FILE"
PROBE_FILE=

printf 'Certbot предложит принять условия Let’s Encrypt. Адрес для уведомлений: %s\n' "$EMAIL"
certbot certonly --webroot --webroot-path "$WEBROOT" \
    --cert-name "$DOMAIN" --email "$EMAIL" --keep-until-expiring \
    -d "$DOMAIN" -d "www.$DOMAIN"

# The HTTPS template must never be enabled before both certificate files exist.
[[ -s $CERT_DIR/fullchain.pem && -s $CERT_DIR/privkey.pem ]] \
    || die "Сертификат не создан в $CERT_DIR; конфигурация nginx сохранена."
backup_candidate=$(mktemp /etc/nginx/sites-available/zinaidapsy.before-https.XXXXXXXX)
if ! cp -p -- "$SITE_AVAILABLE" "$backup_candidate"; then
    rm -f -- "$backup_candidate"
    die 'Не удалось сохранить конфигурацию nginx; HTTPS не включён.'
fi
NGINX_BACKUP=$backup_candidate
install -m 0644 "$DEPLOY_DIR/nginx.conf" "$SITE_AVAILABLE"
nginx -t
systemctl reload nginx.service
rm -f -- "$NGINX_BACKUP"
NGINX_BACKUP=

install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
install -m 0755 "$DEPLOY_DIR/certbot-renew-nginx.sh" \
    /etc/letsencrypt/renewal-hooks/deploy/zinaidapsy-nginx
systemctl enable --now certbot.timer
certbot renew --dry-run --cert-name "$DOMAIN"

expect_status() {
    local url=$1 expected=$2 actual
    actual=$(curl --silent --show-error --noproxy '*' \
        --connect-timeout 10 --max-time 30 --output /dev/null \
        --write-out '%{http_code}' "$url") || die "Не удалось проверить $url."
    [[ $actual == "$expected" ]] || die "$url вернул HTTP $actual, ожидался $expected."
    printf 'HTTP %s: %s\n' "$actual" "$url"
}

for url in "http://$DOMAIN/" "https://www.$DOMAIN/"; do
    actual=$(curl --silent --show-error --noproxy '*' \
        --connect-timeout 10 --max-time 30 --output /dev/null \
        --write-out '%{http_code} %{redirect_url}' "$url") || die "Не удалось проверить редирект $url."
    [[ $actual == "301 https://$DOMAIN/" ]] || die "Некорректный редирект $url: $actual"
    printf 'Редирект проверен: %s\n' "$url"
done
for path in / /robots.txt /sitemap.xml /static/css/output.css; do
    expect_status "https://$DOMAIN$path" 200
done
for path in /.env /db.sqlite3; do
    expect_status "https://$DOMAIN$path" 404
done
systemctl --no-pager status zinaidapsy-web.service nginx.service certbot.timer

printf '\nHTTPS и продление сертификата настроены. Проверьте сайт и Метрику 110198201 в браузере.\n'
printf 'После проверки Telegram/Google Forms включите доставку заявок отдельно:\n'
printf '  sudo systemctl enable --now zinaidapsy-feedback.service\n'

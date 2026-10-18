# Установка через Git на новый сервер

Код: `git@github.com:d1vine123/zinaidapsy.git`, ветка `main`.
Сервер: Ubuntu 24.04 LTS, SSH-пользователь с sudo, входящие TCP 22/80/443.
Скрипты рассчитаны на первую установку и откажутся затирать существующую БД.
Полный список зависимостей: `deploy/requirements-production.txt`.

## 1. На Mac: опубликовать код

В старой истории Git есть копии SQLite с учётной записью. Используйте закрытый
репозиторий. Следующие команды перестают отслеживать БД, загруженные изображения
и вложенное зеркало Git, сохраняя местные файлы. Историю они не переписывают.

```bash
cd /Users/kirillversan/zinaidapsy
git rm -r --cached --ignore-unmatch media zinaidapsy.git db.sqlite3.before-import db.sqlite3.empty-backup db.sqlite3.failed-import-backup
git add .gitignore .env.example DEPLOYMENT.md deploy config/settings.py templates/base.html templates/blocks/feedback_block.html wgapps
git diff --cached --stat
git commit -m "Prepare Git deployment and restore production runtime"
git push origin main
```

При ошибке push не применяйте force: сначала разберите расхождение с origin.
Не добавляйте `.env`, `recovery/` и актуальную БД в Git.

## 2. На сервере: дать доступ к GitHub

Создайте отдельный ключ для чтения этого репозитория:

```bash
sudo apt update
sudo apt install -y git
install -d -m 0700 "$HOME/.ssh"
if [ ! -e "$HOME/.ssh/zinaidapsy_github" ]; then
  ssh-keygen -t ed25519 -f "$HOME/.ssh/zinaidapsy_github" -N '' -C zinaidapsy-github
fi
cat "$HOME/.ssh/zinaidapsy_github.pub"
```

На GitHub откройте репозиторий → Settings → Deploy keys → Add deploy key.
Вставьте выведенную строку, название `zinaidapsy-server`; право Allow write access
оставьте выключенным. Это ключ доступа сервера к одному репозиторию.
[Документация GitHub](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys).

Затем на сервере:

```bash
sudo install -d -m 0755 /srv/zinaidapsy
sudo git -c core.sshCommand="ssh -i $HOME/.ssh/zinaidapsy_github -o IdentitiesOnly=yes" clone --branch main git@github.com:d1vine123/zinaidapsy.git /srv/zinaidapsy/app
sudo git -C /srv/zinaidapsy/app config core.sshCommand "ssh -i $HOME/.ssh/zinaidapsy_github -o IdentitiesOnly=yes"
```

Первое SSH-подключение к GitHub предлагает проверить ключ сервера. Закрытый
ключ `zinaidapsy_github` остаётся на VPS; в GitHub добавляется только `.pub`.

## 3. На Mac: перенести данные по SSH

Откройте дополнительную вкладку терминала на Mac. В `SERVER` замените IP и,
если входите другим пользователем, `root`. Используйте свой рабочий способ SSH;
ниже указан ключ, созданный в процессе восстановления.

```bash
cd /Users/kirillversan/zinaidapsy
./venv/bin/python deploy/prepare-data.py
SERVER=root@IP_СЕРВЕРА
SSH_KEY="$PWD/recovery/2026-10-18/ssh/zinaidapsy-vps"
scp -i "$SSH_KEY" -pr recovery/server-data "$SERVER:zinaidapsy-data"
```

`prepare-data.py` создаёт согласованную копию SQLite, полный набор изображений
и `production.env` с новым SECRET_KEY и сохранёнными интеграциями. Он не меняет
исходную БД. Каталог защищён и исключён из Git. При повторном запуске существующий
пакет не затирается: можно использовать уже созданный каталог.

## 4. На сервере: установить приложение

```bash
sudo bash /srv/zinaidapsy/app/deploy/install-server.sh "$HOME/zinaidapsy-data"
```

Установщик создаёт окружение Python, применяет миграции, собирает статику,
настраивает Gunicorn/systemd и временный HTTP-сайт для выпуска сертификата.
До включения HTTPS основной URL отвечает 503. БД и настройки находятся в
`/srv/zinaidapsy/private/`, загрузки — в `/srv/zinaidapsy/shared/media/`.
Код принадлежит root; сервис читает его и пишет только данные.

## 5. DNS, HTTPS и формы

В DNS домена измените A для `@` и `www` на IP нового VPS (либо CNAME `www` на
`zinaidapsy.ru.`). Старую AAAA уберите, если не настраиваете IPv6 нового сервера.
MX/TXT и другие почтовые записи сохраните. Откройте 80/443 в сетевых правилах
провайдера, сохранив рабочий SSH-порт.

Когда оба имени направлены на VPS, выполните в интерактивной SSH-сессии:

```bash
sudo bash /srv/zinaidapsy/app/deploy/enable-https.sh YOUR_EMAIL
```

Замените `YOUR_EMAIL` своим адресом. Certbot предложит принять условия
Let’s Encrypt. Скрипт проверит оба имени, установит сертификат и проверит сайт.

Проверьте внешний вид сайта. Затем включите обработчик заявок:

```bash
sudo systemctl enable --now zinaidapsy-feedback.service
sudo systemctl status zinaidapsy-web zinaidapsy-feedback nginx --no-pager
```

Отправьте явно помеченную тестовую заявку и проверьте доставку в свои Telegram
и Google Forms. Метрика сохраняет прежний номер 110198201.

## Диагностика

```bash
sudo journalctl -u zinaidapsy-web -n 80 --no-pager
sudo journalctl -u zinaidapsy-feedback -n 80 --no-pager
sudo nginx -t
```

Для следующих обновлений переносить БД и media повторно не нужно: опубликуйте
новый коммит, получите его на VPS, сделайте резервную копию БД, примените миграции
и перезапустите сервисы. Пример первой установки не запускайте повторно.

import urllib.request
import urllib.parse
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect

logger = logging.getLogger(__name__)


def _submit_to_google_form(name, phone, source, message, contact_method="", telegram_username=""):
    """Отправляет данные в Google Form (без авторизации). Молча игнорирует ошибки."""
    form_id = getattr(settings, "GOOGLE_FORM_ID", "")
    if not form_id:
        return
    entry_name             = getattr(settings, "GOOGLE_ENTRY_NAME", "")
    entry_phone            = getattr(settings, "GOOGLE_ENTRY_PHONE", "")
    entry_message          = getattr(settings, "GOOGLE_ENTRY_MESSAGE", "")
    entry_source           = getattr(settings, "GOOGLE_ENTRY_SOURCE", "")
    entry_contact_method   = getattr(settings, "GOOGLE_ENTRY_CONTACT_METHOD", "")
    entry_telegram_username = getattr(settings, "GOOGLE_ENTRY_TELEGRAM_USERNAME", "")
    try:
        data = {}
        if entry_name:             data[entry_name]             = name
        if entry_phone:            data[entry_phone]            = phone
        if entry_message:          data[entry_message]          = message
        if entry_source:           data[entry_source]           = source
        if entry_contact_method:   data[entry_contact_method]   = contact_method
        if entry_telegram_username: data[entry_telegram_username] = telegram_username
        payload = urllib.parse.urlencode(data).encode()
        url = f"https://docs.google.com/forms/d/e/{form_id}/formResponse"
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Referer", url)
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        logger.exception("Google Forms submit failed")


@require_POST
@csrf_protect
def feedback_submit(request):
    name             = request.POST.get("name", "").strip()
    phone            = request.POST.get("phone", "").strip()
    message          = request.POST.get("message", "").strip()
    source           = request.POST.get("source", "").strip()
    contact_methods  = [method.strip() for method in request.POST.getlist("contact_method") if method.strip()]
    contact_method   = ", ".join(contact_methods)
    telegram_username = request.POST.get("telegram_username", "").strip()

    if not name or not phone:
        return JsonResponse({"ok": False, "error": "Заполните обязательные поля"}, status=400)

    # ── Telegram ────────────────────────────────────────────────────────────
    text = "📩 <b>Новая заявка с сайта</b>"
    if source:
        text += f"\n<b>Раздел:</b> {source}"
    text += f"\n\n<b>Имя:</b> {name}\n<b>Телефон:</b> {phone}"
    if contact_method:
        text += f"\n<b>Способы связи:</b> {contact_method}"
        if "Telegram" in contact_methods and telegram_username:
            text += f"\n<b>Telegram:</b> {telegram_username}"
    if message:
        text += f"\n<b>Сообщение:</b> {message}"

    bot_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id   = getattr(settings, "TELEGRAM_CHAT_ID", "")

    if not bot_token or not chat_id:
        return JsonResponse({"ok": False, "error": "Telegram не настроен"}, status=500)

    payload = urllib.parse.urlencode({
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "HTML",
    }).encode()

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    req = urllib.request.Request(url, data=payload, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                return JsonResponse({"ok": False, "error": "Telegram error"}, status=500)
    except Exception:
        return JsonResponse({"ok": False, "error": "Ошибка соединения"}, status=500)

    # ── Google Forms → Sheets (не блокирует ответ при ошибке) ─────────────
    _submit_to_google_form(name, phone, source, message, contact_method, telegram_username)

    return JsonResponse({"ok": True})

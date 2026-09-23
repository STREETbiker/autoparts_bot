import os
import asyncio
import logging
import datetime
import time
from zoneinfo import ZoneInfo
from threading import Thread, Lock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)


# ==================================================
# НАСТРОЙКИ
# ==================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = 1112183569

SHEET_ID = "19klP5Uw-_gLe8LS9N5-dzs_53qhAucQisACPMGLbpzs"
WORKSHEET_NAME = "Запросы"
GOOGLE_CREDENTIALS_FILE = "/etc/secrets/service_account.json"

TIMEZONE = ZoneInfo("Europe/Chisinau")

WATCHDOG_INTERVAL = 60
WATCHDOG_MAX_FAILURES = 3
WATCHDOG_STALE_SECONDS = 180

SOURCE_NAMES = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "tiktok": "TikTok",
    "google": "Google",
    "whatsapp": "WhatsApp",
    "shop_qr": "QR в магазине",
    "card": "Визитка",
}


def get_source(context):
    if context.args:
        source_code = context.args[0].strip().lower()
        return SOURCE_NAMES.get(source_code, source_code)
    return "Telegram / прямой"


def get_request_keyboard(add_text="➕ Добавить к запросу"):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(add_text, callback_data="add_more")],
            [InlineKeyboardButton("🆕 Новый запрос", callback_data="new_request")],
        ]
    )


def get_reply_keyboard(client_chat_id):
    # Числовой ID находится прямо в callback_data, поэтому уже отправленная
    # кнопка продолжает указывать на клиента после перезапуска приложения.
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(
                "💬 Ответить клиенту",
                callback_data=f"reply:{int(client_chat_id)}",
            )
        ]]
    )


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

if not BOT_TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN")


# ==================================================
# HEALTH SERVER / WATCHDOG
# ==================================================

health_lock = Lock()
health_state = {
    "started": False,
    "telegram_ok": False,
    "last_watchdog_ok": 0.0,
    "failures": 0,
}


def set_health(**kwargs):
    with health_lock:
        health_state.update(kwargs)


def get_health():
    with health_lock:
        return dict(health_state)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        state = get_health()
        watchdog_fresh = (
            state["last_watchdog_ok"] > 0
            and time.time() - state["last_watchdog_ok"] < WATCHDOG_STALE_SECONDS
        )
        healthy = state["started"] and state["telegram_ok"] and watchdog_fresh
        status = 200 if healthy else 503
        body = (
            "OK - AutoPartsBot and Telegram are healthy"
            if healthy
            else "ERROR - AutoPartsBot Telegram health check failed"
        )
        self.send_response(status)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Health server запущен на порту %s", port)


# ==================================================
# GOOGLE SHEETS
# ==================================================

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    GOOGLE_CREDENTIALS_FILE,
    scope,
)
google_client = gspread.authorize(creds)
sheet = google_client.open_by_key(SHEET_ID).worksheet(WORKSHEET_NAME)


async def sheet_append_row(data):
    await asyncio.to_thread(sheet.append_row, data, value_input_option="RAW")


async def sheet_get_last_row():
    values = await asyncio.to_thread(sheet.get_all_values)
    return len(values)


async def sheet_get_cell(row, column):
    cell = await asyncio.to_thread(sheet.cell, row, column)
    return cell.value


async def sheet_update_cell(row, column, value):
    await asyncio.to_thread(sheet.update_cell, row, column, value)


# ==================================================
# СОСТОЯНИЯ ДИАЛОГА
# ==================================================

(
    MARK,
    MODEL,
    YEAR,
    ENGINE,
    FUEL,
    VIN,
    PARTS,
    PHONE,
    CLIENT,
    CITY,
    ADD_MORE,
) = range(11)


async def begin_request(message, context, source):
    context.user_data.clear()
    context.user_data["source"] = source
    await message.reply_text(
        "Добро пожаловать в магазин!\n\n"
        "Для подбора запчастей укажите марку автомобиля:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return MARK


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    source = get_source(context)
    logger.info(
        "Получен /start от Telegram ID %s | Источник: %s",
        update.effective_user.id,
        source,
    )
    return await begin_request(update.message, context, source)


async def new_request_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    source = context.user_data.get("source", "Telegram / прямой")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        logger.exception("Не удалось убрать старые inline-кнопки")
    logger.info(
        "Новый запрос по кнопке | Telegram ID %s | Источник: %s",
        update.effective_user.id,
        source,
    )
    return await begin_request(query.message, context, source)


async def get_mark(update, context):
    context.user_data["mark"] = update.message.text.strip()
    await update.message.reply_text("Введите модель автомобиля:")
    return MODEL


async def get_model(update, context):
    context.user_data["model"] = update.message.text.strip()
    await update.message.reply_text("Введите год выпуска:")
    return YEAR


async def get_year(update, context):
    context.user_data["year"] = update.message.text.strip()
    await update.message.reply_text("Введите объём двигателя (например, 1.6):")
    return ENGINE


async def get_engine(update, context):
    context.user_data["engine"] = update.message.text.strip()
    keyboard = [["Бензин", "Дизель"], ["Газ", "Электричество"]]
    await update.message.reply_text(
        "Выберите тип топлива:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    return FUEL


async def get_fuel(update, context):
    context.user_data["fuel"] = update.message.text.strip()
    await update.message.reply_text(
        "Введите VIN автомобиля:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return VIN


async def get_vin(update, context):
    context.user_data["vin"] = update.message.text.strip().upper()
    await update.message.reply_text(
        "Какие запчасти Вас интересуют?\n\n"
        "Укажите названия или артикулы, если они Вам известны:"
    )
    return PARTS


async def get_parts(update, context):
    context.user_data["parts"] = update.message.text.strip()
    phone_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Отправить номер телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        "Укажите Ваш контактный номер телефона.\n\n"
        "Можно ввести номер вручную или нажать кнопку ниже:",
        reply_markup=phone_keyboard,
    )
    return PHONE


async def get_phone(update, context):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()
    phone = phone.replace(" ", "")
    if phone.startswith("373"):
        phone = "+" + phone
    context.user_data["phone"] = phone
    await update.message.reply_text(
        "Как к Вам обращаться?",
        reply_markup=ReplyKeyboardRemove(),
    )
    return CLIENT


async def get_client(update, context):
    context.user_data["client"] = update.message.text.strip()
    await update.message.reply_text("Укажите Ваш город:")
    return CITY


async def get_city(update, context):
    context.user_data["city"] = update.message.text.strip()
    user = update.effective_user
    client_chat_id = update.effective_chat.id
    telegram_user = f"@{user.username}" if user.username else (user.full_name or str(user.id))
    date = datetime.datetime.now(TIMEZONE).strftime("%d.%m.%Y %H:%M")
    source = context.user_data.get("source", "Telegram / прямой")

    data = [
        date,
        context.user_data["mark"],
        context.user_data["model"],
        context.user_data["year"],
        context.user_data["engine"],
        context.user_data["fuel"],
        context.user_data["vin"],
        context.user_data["parts"],
        context.user_data["phone"],
        context.user_data["client"],
        context.user_data["city"],
        source,
    ]

    try:
        await sheet_append_row(data)
        context.user_data["sheet_row"] = await sheet_get_last_row()
        logger.info("Новый запрос записан в Google Sheets | Источник: %s", source)
    except Exception:
        logger.exception("Ошибка записи запроса в Google Sheets")
        await update.message.reply_text(
            "Произошла ошибка при отправке запроса.\n"
            "Попробуйте ещё раз немного позже.",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.clear()
        return ConversationHandler.END

    admin_message = (
        "🔔 НОВЫЙ ЗАПРОС\n\n"
        f"👤 Клиент: {context.user_data['client']}\n"
        f"📞 Телефон: {context.user_data['phone']}\n"
        f"📍 Город: {context.user_data['city']}\n"
        f"📊 Источник: {source}\n"
        f"💬 Telegram: {telegram_user}\n"
        f"🆔 Telegram ID: {client_chat_id}\n\n"
        f"🚗 Марка: {context.user_data['mark']}\n"
        f"🚘 Модель: {context.user_data['model']}\n"
        f"📅 Год: {context.user_data['year']}\n"
        f"⚙️ Двигатель: {context.user_data['engine']}\n"
        f"⛽ Топливо: {context.user_data['fuel']}\n"
        f"🔢 VIN: {context.user_data['vin']}\n\n"
        "🔧 Запчасти:\n"
        f"{context.user_data['parts']}"
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
            reply_markup=get_reply_keyboard(client_chat_id),
        )
    except Exception:
        logger.exception("Не удалось отправить уведомление администратору")

    context.user_data["waiting_addition"] = False
    await update.message.reply_text(
        "✅ Спасибо! Ваш запрос отправлен.\n\n"
        "Мы свяжемся с Вами в ближайшее время.\n\n"
        "Если хотите добавить запчасти или комментарий к текущему запросу, "
        "нажмите кнопку ниже.\n\n"
        "Для оформления другой заявки нажмите «🆕 Новый запрос».",
        reply_markup=get_request_keyboard(),
    )
    return ADD_MORE


async def add_more_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        logger.exception("Не удалось убрать старые inline-кнопки")
    context.user_data["waiting_addition"] = True
    await query.message.reply_text(
        "Укажите дополнительные запчасти или напишите комментарий:"
    )
    return ADD_MORE


def client_details(context, user):
    telegram_user = f"@{user.username}" if user.username else (user.full_name or str(user.id))
    return (
        f"👤 Клиент: {context.user_data.get('client', user.full_name or '')}\n"
        f"📞 Телефон: {context.user_data.get('phone', '')}\n"
        f"📍 Город: {context.user_data.get('city', '')}\n"
        f"📊 Источник: {context.user_data.get('source', 'Telegram / прямой')}\n"
        f"💬 Telegram: {telegram_user}\n"
        f"🆔 Telegram ID: {user.id}\n"
        f"🔢 VIN: {context.user_data.get('vin', '')}"
    )


async def add_more_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    client_chat_id = update.effective_chat.id

    # Обычный текст без кнопки — сообщение администратору, а не дополнение в таблицу.
    if not context.user_data.get("waiting_addition"):
        admin_message = (
            "💬 СООБЩЕНИЕ ОТ КЛИЕНТА\n\n"
            f"{client_details(context, user)}\n\n"
            "Сообщение:\n"
            f"{text}"
        )
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_message,
                reply_markup=get_reply_keyboard(client_chat_id),
            )
            await update.message.reply_text(
                "✅ Ваше сообщение отправлено менеджеру.",
                reply_markup=get_request_keyboard(),
            )
        except Exception:
            logger.exception("Не удалось переслать сообщение клиента администратору")
            await update.message.reply_text(
                "Не удалось отправить сообщение. Попробуйте ещё раз немного позже."
            )
        return ADD_MORE

    addition = text
    row = context.user_data.get("sheet_row")
    try:
        if row:
            current_parts = await sheet_get_cell(row, 8) or ""
            new_parts = current_parts + "\nДополнение: " + addition
            await sheet_update_cell(row, 8, new_parts)
            logger.info("Дополнение добавлено в Google Sheets")
        else:
            logger.warning("Не найден sheet_row для дополнения")
    except Exception:
        logger.exception("Ошибка добавления дополнения в Google Sheets")

    admin_add_message = (
        "📝 ДОПОЛНЕНИЕ К ЗАПРОСУ\n\n"
        f"{client_details(context, user)}\n\n"
        "➕ Дополнение:\n"
        f"{addition}"
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_add_message,
            reply_markup=get_reply_keyboard(client_chat_id),
        )
    except Exception:
        logger.exception("Не удалось отправить дополнение администратору")

    context.user_data["waiting_addition"] = False
    await update.message.reply_text(
        "Спасибо! Дополнение к Вашему запросу отправлено.\n\n"
        "Если хотите добавить ещё что-нибудь, нажмите кнопку ниже.",
        reply_markup=get_request_keyboard("➕ Добавить ещё"),
    )
    return ADD_MORE


# ==================================================
# ОТВЕТ АДМИНИСТРАТОРА КЛИЕНТУ
# ==================================================

async def reply_to_client_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id != ADMIN_CHAT_ID:
        await query.answer("Эта кнопка доступна только администратору.", show_alert=True)
        return

    await query.answer()
    try:
        client_chat_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        logger.warning("Некорректный callback ответа: %r", query.data)
        await query.message.reply_text("Не удалось определить клиента для ответа.")
        return

    # Адрес хранится отдельно в user_data администратора. Новое нажатие всегда
    # явно заменяет адресата, поэтому ответы нескольким клиентам не смешиваются.
    context.user_data["reply_client_chat_id"] = client_chat_id
    await query.message.reply_text(
        f"Введите ответ клиенту (Telegram ID: {client_chat_id}).\n\n"
        "Чтобы отменить ответ, отправьте /cancel_reply."
    )


async def cancel_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    context.user_data.pop("reply_client_chat_id", None)
    await update.message.reply_text("Ответ клиенту отменён.")


async def admin_reply_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    client_chat_id = context.user_data.get("reply_client_chat_id")
    if client_chat_id is None:
        return

    reply_text = update.message.text.strip()
    try:
        await context.bot.send_message(
            chat_id=client_chat_id,
            text="💬 EUROPAplus:\n\n" + reply_text,
        )
    except Exception:
        logger.exception("Не удалось отправить ответ клиенту %s", client_chat_id)
        await update.message.reply_text(
            "❌ Ответ не отправлен. Возможно, клиент заблокировал бота.\n"
            "Адресат сохранён — можно повторить отправку или использовать /cancel_reply."
        )
        return

    context.user_data.pop("reply_client_chat_id", None)
    await update.message.reply_text(
        f"✅ Ответ отправлен клиенту (Telegram ID: {client_chat_id})."
    )


# ==================================================
# WATCHDOG И ОШИБКИ
# ==================================================

async def watchdog(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.get_me()
        set_health(
            telegram_ok=True,
            last_watchdog_ok=time.time(),
            failures=0,
        )
    except Exception:
        state = get_health()
        failures = state["failures"] + 1
        set_health(telegram_ok=False, failures=failures)
        logger.exception("Watchdog: Telegram API недоступен (%s)", failures)
        if failures >= WATCHDOG_MAX_FAILURES:
            logger.critical("Watchdog: превышен лимит ошибок Telegram API")


async def post_init(application: Application):
    await application.bot.get_me()
    set_health(
        started=True,
        telegram_ok=True,
        last_watchdog_ok=time.time(),
        failures=0,
    )
    application.job_queue.run_repeating(
        watchdog,
        interval=WATCHDOG_INTERVAL,
        first=WATCHDOG_INTERVAL,
        name="telegram_watchdog",
    )
    logger.info("Telegram-бот успешно запущен")


async def error_handler(update, context):
    logger.error("Необработанная ошибка", exc_info=context.error)


def main():
    start_health_server()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Эти обработчики стоят раньше ConversationHandler, чтобы администратор
    # мог отвечать независимо от диалогов клиентов.
    application.add_handler(
        CallbackQueryHandler(reply_to_client_button, pattern=r"^reply:-?\d+$"),
        group=0,
    )
    application.add_handler(
        CommandHandler("cancel_reply", cancel_admin_reply, filters.Chat(ADMIN_CHAT_ID)),
        group=0,
    )
    application.add_handler(
        MessageHandler(filters.Chat(ADMIN_CHAT_ID) & filters.TEXT & ~filters.COMMAND, admin_reply_text),
        group=0,
    )

    text = filters.TEXT & ~filters.COMMAND
    conversation = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            # Entry point обязателен: кнопка запускает анкету и после окончания
            # старого ConversationHandler, и после перезапуска процесса.
            CallbackQueryHandler(new_request_button, pattern="^new_request$"),
        ],
        states={
            MARK: [MessageHandler(text, get_mark)],
            MODEL: [MessageHandler(text, get_model)],
            YEAR: [MessageHandler(text, get_year)],
            ENGINE: [MessageHandler(text, get_engine)],
            FUEL: [MessageHandler(text, get_fuel)],
            VIN: [MessageHandler(text, get_vin)],
            PARTS: [MessageHandler(text, get_parts)],
            PHONE: [MessageHandler((filters.CONTACT | text), get_phone)],
            CLIENT: [MessageHandler(text, get_client)],
            CITY: [MessageHandler(text, get_city)],
            ADD_MORE: [
                CallbackQueryHandler(add_more_button, pattern="^add_more$"),
                CallbackQueryHandler(new_request_button, pattern="^new_request$"),
                MessageHandler(text, add_more_text),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )
    application.add_handler(conversation, group=1)
    application.add_error_handler(error_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

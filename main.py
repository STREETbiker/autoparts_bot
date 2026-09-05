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
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
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


# ==================================================
# WATCHDOG
# ==================================================

WATCHDOG_INTERVAL = 60
WATCHDOG_MAX_FAILURES = 3
WATCHDOG_STALE_SECONDS = 180


# ==================================================
# ИСТОЧНИКИ ЗАЯВОК
# ==================================================

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
    """
    Определяет источник клиента из Telegram deep-link.

    Например:
    https://t.me/EplusA_bot?start=instagram
    """

    if context.args:
        source_code = context.args[0].strip().lower()

        return SOURCE_NAMES.get(
            source_code,
            source_code,
        )

    return "Telegram / прямой"


# ==================================================
# ЛОГИ
# ==================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# Не показываем URL Telegram API с токеном
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# ==================================================
# ПРОВЕРКА TOKEN
# ==================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "Не задана переменная окружения BOT_TOKEN"
    )


# ==================================================
# СОСТОЯНИЕ HEALTH / WATCHDOG
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


# ==================================================
# HEALTH SERVER ДЛЯ RENDER
# ==================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        state = get_health()

        now = time.time()

        watchdog_fresh = (
            state["last_watchdog_ok"] > 0
            and
            now - state["last_watchdog_ok"]
            < WATCHDOG_STALE_SECONDS
        )

        healthy = (
            state["started"]
            and state["telegram_ok"]
            and watchdog_fresh
        )

        if healthy:
            status = 200
            body = (
                "OK - AutoPartsBot and Telegram "
                "are healthy"
            )
        else:
            status = 503
            body = (
                "ERROR - AutoPartsBot Telegram "
                "health check failed"
            )

        self.send_response(status)

        self.send_header(
            "Content-type",
            "text/plain; charset=utf-8",
        )

        self.end_headers()

        self.wfile.write(
            body.encode("utf-8")
        )

    def log_message(self, format, *args):
        return


def start_health_server():

    port = int(
        os.environ.get("PORT", "10000")
    )

    server = ThreadingHTTPServer(
        ("0.0.0.0", port),
        HealthHandler,
    )

    thread = Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    logger.info(
        "Health server запущен на порту %s",
        port,
    )


# ==================================================
# GOOGLE SHEETS
# ==================================================

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

creds = (
    ServiceAccountCredentials
    .from_json_keyfile_name(
        GOOGLE_CREDENTIALS_FILE,
        scope,
    )
)

google_client = gspread.authorize(creds)

sheet = (
    google_client
    .open_by_key(SHEET_ID)
    .worksheet(WORKSHEET_NAME)
)


# ==================================================
# ASYNC GOOGLE SHEETS
# ==================================================

async def sheet_append_row(data):

    await asyncio.to_thread(
        sheet.append_row,
        data,
        value_input_option="RAW",
    )


async def sheet_get_last_row():

    values = await asyncio.to_thread(
        sheet.get_all_values
    )

    return len(values)


async def sheet_get_cell(row, column):

    cell = await asyncio.to_thread(
        sheet.cell,
        row,
        column,
    )

    return cell.value


async def sheet_update_cell(
    row,
    column,
    value,
):

    await asyncio.to_thread(
        sheet.update_cell,
        row,
        column,
        value,
    )


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


# ==================================================
# /START
# ==================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    # Сначала определяем источник.
    # Это нужно сделать ДО context.user_data.clear()
    source = get_source(context)

    context.user_data.clear()

    # Сохраняем источник на всё время заполнения заявки
    context.user_data["source"] = source

    logger.info(
        "Получен /start от Telegram ID %s | Источник: %s",
        update.effective_user.id,
        source,
    )

    await update.message.reply_text(
        "Добро пожаловать в магазин!\n\n"
        "Для подбора запчастей укажите марку автомобиля:",
        reply_markup=ReplyKeyboardRemove(),
    )

    return MARK


# ==================================================
# МАРКА
# ==================================================

async def get_mark(
    update,
    context,
):

    context.user_data["mark"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "Введите модель автомобиля:"
    )

    return MODEL


# ==================================================
# МОДЕЛЬ
# ==================================================

async def get_model(
    update,
    context,
):

    context.user_data["model"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "Введите год выпуска:"
    )

    return YEAR


# ==================================================
# ГОД
# ==================================================

async def get_year(
    update,
    context,
):

    context.user_data["year"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "Введите объём двигателя "
        "(например, 1.6):"
    )

    return ENGINE


# ==================================================
# ДВИГАТЕЛЬ
# ==================================================

async def get_engine(
    update,
    context,
):

    context.user_data["engine"] = (
        update.message.text.strip()
    )

    keyboard = [
        ["Бензин", "Дизель"],
        ["Газ", "Электричество"],
    ]

    await update.message.reply_text(
        "Выберите тип топлива:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )

    return FUEL


# ==================================================
# ТОПЛИВО
# ==================================================

async def get_fuel(
    update,
    context,
):

    context.user_data["fuel"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "Введите VIN автомобиля:",
        reply_markup=ReplyKeyboardRemove(),
    )

    return VIN


# ==================================================
# VIN
# ==================================================

async def get_vin(
    update,
    context,
):

    context.user_data["vin"] = (
        update.message.text
        .strip()
        .upper()
    )

    await update.message.reply_text(
        "Какие запчасти Вас интересуют?\n\n"
        "Укажите названия или артикулы, "
        "если они Вам известны:"
    )

    return PARTS


# ==================================================
# ЗАПЧАСТИ
# ==================================================

async def get_parts(
    update,
    context,
):

    context.user_data["parts"] = (
        update.message.text.strip()
    )

    phone_keyboard = ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    "📱 Отправить номер телефона",
                    request_contact=True,
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    await update.message.reply_text(
        "Укажите Ваш контактный номер телефона.\n\n"
        "Можно ввести номер вручную или нажать "
        "кнопку ниже:",
        reply_markup=phone_keyboard,
    )

    return PHONE


# ==================================================
# ТЕЛЕФОН
# ==================================================

async def get_phone(
    update,
    context,
):

    if update.message.contact:
        phone = (
            update.message
            .contact
            .phone_number
        )
    else:
        phone = (
            update.message
            .text
            .strip()
        )

    phone = phone.replace(" ", "")

    if phone.startswith("373"):
        phone = "+" + phone

    context.user_data["phone"] = phone

    await update.message.reply_text(
        "Как к Вам обращаться?",
        reply_markup=ReplyKeyboardRemove(),
    )

    return CLIENT


# ==================================================
# КЛИЕНТ
# ==================================================

async def get_client(
    update,
    context,
):

    context.user_data["client"] = (
        update.message.text.strip()
    )

    await update.message.reply_text(
        "Укажите Ваш город:"
    )

    return CITY


# ==================================================
# ГОРОД + СОХРАНЕНИЕ ЗАЯВКИ
# ==================================================

async def get_city(
    update,
    context,
):

    context.user_data["city"] = (
        update.message.text.strip()
    )

    user = update.effective_user

    if user.username:
        telegram_user = (
            f"@{user.username}"
        )
    else:
        telegram_user = (
            user.full_name
            or str(user.id)
        )

    date = datetime.datetime.now(
        TIMEZONE
    ).strftime(
        "%d.%m.%Y %H:%M"
    )

    # Источник заявки
    source = context.user_data.get(
        "source",
        "Telegram / прямой",
    )

    # A-L
    data = [
        date,                            # A Дата
        context.user_data["mark"],       # B Марка
        context.user_data["model"],      # C Модель
        context.user_data["year"],       # D Год
        context.user_data["engine"],     # E Двигатель
        context.user_data["fuel"],       # F Топливо
        context.user_data["vin"],        # G VIN
        context.user_data["parts"],      # H Запчасти
        context.user_data["phone"],      # I Телефон
        context.user_data["client"],     # J Клиент
        context.user_data["city"],       # K Город
        source,                          # L Источник
    ]


    # ==================================================
    # GOOGLE SHEETS
    # ==================================================

    try:

        await sheet_append_row(data)

        logger.info(
            "Новый запрос записан "
            "в Google Sheets | Источник: %s",
            source,
        )

        context.user_data["sheet_row"] = (
            await sheet_get_last_row()
        )

    except Exception:

        logger.exception(
            "Ошибка записи запроса "
            "в Google Sheets"
        )

        await update.message.reply_text(
            "Произошла ошибка при отправке запроса.\n"
            "Попробуйте ещё раз немного позже.",
            reply_markup=ReplyKeyboardRemove(),
        )

        context.user_data.clear()

        return ConversationHandler.END


    # ==================================================
    # УВЕДОМЛЕНИЕ АДМИНУ
    # ==================================================

    admin_message = (
        "🔔 НОВЫЙ ЗАПРОС\n\n"

        f"👤 Клиент: "
        f"{context.user_data['client']}\n"

        f"📞 Телефон: "
        f"{context.user_data['phone']}\n"

        f"📍 Город: "
        f"{context.user_data['city']}\n"

        f"📊 Источник: "
        f"{source}\n"

        f"💬 Telegram: "
        f"{telegram_user}\n\n"

        f"🚗 Марка: "
        f"{context.user_data['mark']}\n"

        f"🚘 Модель: "
        f"{context.user_data['model']}\n"

        f"📅 Год: "
        f"{context.user_data['year']}\n"

        f"⚙️ Двигатель: "
        f"{context.user_data['engine']}\n"

        f"⛽ Топливо: "
        f"{context.user_data['fuel']}\n"

        f"🔢 VIN: "
        f"{context.user_data['vin']}\n\n"

        "🔧 Запчасти:\n"
        f"{context.user_data['parts']}"
    )

    try:

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
        )

    except Exception:

        logger.exception(
            "Не удалось отправить "
            "уведомление администратору"
        )


    # ==================================================
    # ФИНАЛЬНОЕ СООБЩЕНИЕ
    # ==================================================

    add_keyboard = ReplyKeyboardMarkup(
        [
            ["➕ Добавить к запросу"]
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

    await update.message.reply_text(
        "Спасибо! Ваш запрос отправлен. "
        "Мы свяжемся с Вами в ближайшее время.\n\n"

        "Если хотите отправить новый запрос, "
        "используйте команду /start.\n\n"

        "Если хотите добавить запчасти или комментарий "
        "к текущему запросу, нажмите кнопку ниже.",

        reply_markup=add_keyboard,
    )

    return ADD_MORE


# ==================================================
# ДОПОЛНЕНИЕ К ЗАПРОСУ
# ==================================================

async def add_more(
    update,
    context,
):

    text = (
        update.message.text.strip()
    )

    # Нажатие кнопки
    if text == "➕ Добавить к запросу":

        await update.message.reply_text(
            "Укажите дополнительные запчасти "
            "или напишите комментарий:",
            reply_markup=ReplyKeyboardRemove(),
        )

        context.user_data[
            "waiting_addition"
        ] = True

        return ADD_MORE


    # Получили текст дополнения
    if context.user_data.get(
        "waiting_addition"
    ):

        addition = text

        row = context.user_data.get(
            "sheet_row"
        )

        try:

            if row:

                # H = Запчасти
                current_parts = (
                    await sheet_get_cell(
                        row,
                        8,
                    )
                    or ""
                )

                new_parts = (
                    current_parts
                    + "\n"
                    + "Дополнение: "
                    + addition
                )

                await sheet_update_cell(
                    row,
                    8,
                    new_parts,
                )

                logger.info(
                    "Дополнение добавлено "
                    "в Google Sheets"
                )

        except Exception:

            logger.exception(
                "Ошибка добавления дополнения "
                "в Google Sheets"
            )


        # ==================================================
        # УВЕДОМЛЕНИЕ АДМИНУ О ДОПОЛНЕНИИ
        # ==================================================

        source = context.user_data.get(
            "source",
            "Telegram / прямой",
        )

        admin_add_message = (
            "📝 ДОПОЛНЕНИЕ К ЗАПРОСУ\n\n"

            f"👤 Клиент: "
            f"{context.user_data.get('client', '')}\n"

            f"📞 Телефон: "
            f"{context.user_data.get('phone', '')}\n"

            f"📍 Город: "
            f"{context.user_data.get('city', '')}\n"

            f"📊 Источник: "
            f"{source}\n"

            f"🔢 VIN: "
            f"{context.user_data.get('vin', '')}\n\n"

            "➕ Дополнение:\n"
            f"{addition}"
        )

        try:

            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_add_message,
            )

        except Exception:

            logger.exception(
                "Не удалось отправить "
                "дополнение администратору"
            )


        # Кнопку оставляем
        add_keyboard = ReplyKeyboardMarkup(
            [
                ["➕ Добавить к запросу"]
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
        )

        await update.message.reply_text(
            "Спасибо! Дополнение к Вашему запросу "
            "отправлено.\n\n"

            "Если хотите добавить ещё что-нибудь, "
            "нажмите кнопку "
            "«➕ Добавить к запросу».",

            reply_markup=add_keyboard,
        )

        context.user_data[
            "waiting_addition"
        ] = False

        return ADD_MORE

    return ADD_MORE


# ==================================================
# /CANCEL
# ==================================================

async def cancel(
    update,
    context,
):

    context.user_data.clear()

    await update.message.reply_text(
        "Запрос отменён.\n\n"
        "Чтобы начать заново, "
        "используйте команду /start.",
        reply_markup=ReplyKeyboardRemove(),
    )

    return ConversationHandler.END


# ==================================================
# ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК
# ==================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Необработанная ошибка Telegram",
        exc_info=context.error,
    )


# ==================================================
# TELEGRAM WATCHDOG
# ==================================================

async def telegram_watchdog(
    application,
):

    failures = 0

    logger.info(
        "Telegram watchdog запущен"
    )

    while True:

        try:

            await asyncio.wait_for(
                application.bot.get_me(),
                timeout=20,
            )

            failures = 0

            set_health(
                started=True,
                telegram_ok=True,
                last_watchdog_ok=time.time(),
                failures=0,
            )

            logger.info(
                "Watchdog: Telegram OK"
            )

        except asyncio.CancelledError:
            raise

        except Exception:

            failures += 1

            set_health(
                telegram_ok=False,
                failures=failures,
            )

            logger.exception(
                "Watchdog: ошибка Telegram "
                "(%s/%s)",
                failures,
                WATCHDOG_MAX_FAILURES,
            )

            if (
                failures
                >= WATCHDOG_MAX_FAILURES
            ):

                logger.critical(
                    "Telegram не отвечает %s "
                    "проверок подряд. "
                    "Завершаю процесс для "
                    "автоматического перезапуска Render.",
                    failures,
                )

                os._exit(1)

        await asyncio.sleep(
            WATCHDOG_INTERVAL
        )


# ==================================================
# POST INIT
# ==================================================

async def post_init(
    application,
):

    set_health(
        started=True,
        telegram_ok=True,
        last_watchdog_ok=time.time(),
        failures=0,
    )

    application.create_task(
        telegram_watchdog(
            application
        )
    )

    logger.info(
        "AutoPartsBot полностью "
        "инициализирован"
    )


# ==================================================
# ЗАПУСК
# ==================================================

def main():

    start_health_server()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .connect_timeout(20)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(20)
        .build()
    )

    conversation_handler = (
        ConversationHandler(

            entry_points=[
                CommandHandler(
                    "start",
                    start,
                )
            ],

            states={

                MARK: [
                    MessageHandler(
                        filters.TEXT
                        & ~filters.COMMAND,
                        get_mark,
                    )
                ],

                MODEL: [
                    MessageHandler(
                        filters.TEXT
                        & ~filters.COMMAND,
                        get_model,
                    )
                ],

                YEAR: [
                    MessageHandler(
                        filters.TEXT
                        & ~filters.COMMAND,
                        get_year,
                    )
                ],

                ENGINE: [
                    MessageHandler(
                        filters.TEXT
                        & ~filters.COMMAND,
                        get_engine,
                    )
                ],

                FUEL: [
                    MessageHandler(
                        filters.TEXT
                        & ~filters.COMMAND,
                        get_fuel,
                    )
                ],

                VIN: [
                    MessageHandler(
                        filters.TEXT
                        & ~filters.COMMAND,
                        get_vin,
                    )
                ],

                PARTS: [
                    MessageHandler(
                        filters.TEXT
                        & ~filters.COMMAND,
                        get_parts,
                    )
                ],

                PHONE: [
                    MessageHandler(
                        (
                            filters.CONTACT
                            |
                            (
                                filters.TEXT
                                & ~filters.COMMAND
                            )
                        ),
                        get_phone,
                    )
                ],

                CLIENT: [
                    MessageHandler(
                        filters.TEXT
                        & ~filters.COMMAND,
                        get_client,
                    )
                ],

                CITY: [
                    MessageHandler(
                        filters.TEXT
                        & ~filters.COMMAND,
                        get_city,
                    )
                ],

                ADD_MORE: [
                    MessageHandler(
                        filters.TEXT
                        & ~filters.COMMAND,
                        add_more,
                    )
                ],
            },

            fallbacks=[
                CommandHandler(
                    "cancel",
                    cancel,
                )
            ],

            allow_reentry=True,
        )
    )

    application.add_handler(
        conversation_handler
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "AutoPartsBot запускается..."
    )

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()

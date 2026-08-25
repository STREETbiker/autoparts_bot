import os
import logging
import datetime
from zoneinfo import ZoneInfo

import gspread

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

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


# ==================================================
# ЛОГИ
# ==================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ==================================================
# ПРОВЕРКА TOKEN
# ==================================================

if not BOT_TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN")


# ==================================================
# HEALTH SERVER ДЛЯ RENDER + UPTIMEROBOT
# ==================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header(
            "Content-type",
            "text/plain; charset=utf-8"
        )
        self.end_headers()

        self.wfile.write(
            "AutoPartsBot is running".encode("utf-8")
        )

    def log_message(self, format, *args):
        return


def start_health_server():

    port = int(os.environ.get("PORT", "10000"))

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
        port
    )


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

client = gspread.authorize(creds)

sheet = client.open_by_key(
    SHEET_ID
).worksheet(
    WORKSHEET_NAME
)


# ==================================================
# СОСТОЯНИЯ
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

    context.user_data.clear()

    logger.info(
        "Новый запрос от пользователя ID %s",
        update.effective_user.id,
    )

    await update.message.reply_text(
        "Приветствуем!\n\n"
        "Укажите марку автомобиля:",
        reply_markup=ReplyKeyboardRemove(),
    )

    return MARK


# ==================================================
# МАРКА
# ==================================================

async def get_mark(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["mark"] = update.message.text.strip()

    await update.message.reply_text(
        "Введите модель автомобиля:"
    )

    return MODEL


# ==================================================
# МОДЕЛЬ
# ==================================================

async def get_model(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["model"] = update.message.text.strip()

    await update.message.reply_text(
        "Введите год выпуска:"
    )

    return YEAR


# ==================================================
# ГОД
# ==================================================

async def get_year(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["year"] = update.message.text.strip()

    await update.message.reply_text(
        "Введите объём двигателя (например, 1.6):"
    )

    return ENGINE


# ==================================================
# ДВИГАТЕЛЬ
# ==================================================

async def get_engine(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["engine"] = update.message.text.strip()

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
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["fuel"] = update.message.text.strip()

    await update.message.reply_text(
        "Введите VIN автомобиля:",
        reply_markup=ReplyKeyboardRemove(),
    )

    return VIN


# ==================================================
# VIN
# ==================================================

async def get_vin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["parts"] = update.message.text.strip()

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
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

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


# ==================================================
# КЛИЕНТ
# ==================================================

async def get_client(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["client"] = update.message.text.strip()

    await update.message.reply_text(
        "Укажите Ваш город:"
    )

    return CITY


# ==================================================
# ГОРОД + СОХРАНЕНИЕ ЗАЯВКИ
# ==================================================

async def get_city(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data["city"] = update.message.text.strip()

    user = update.effective_user

    if user.username:
        telegram_user = f"@{user.username}"
    else:
        telegram_user = user.full_name or str(user.id)

    date = datetime.datetime.now(
        ZoneInfo("Europe/Chisinau")
    ).strftime("%d.%m.%Y %H:%M")

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
    ]

    try:
        sheet.append_row(
            data,
            value_input_option="RAW",
        )

        logger.info(
            "Новый запрос записан в Google Sheets"
        )

        # Сохраняем номер строки текущей заявки
        context.user_data["sheet_row"] = len(sheet.get_all_values())

    except Exception:

        logger.exception(
            "Ошибка записи запроса в Google Sheets"
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
        f"👤 Клиент: {context.user_data['client']}\n"
        f"📞 Телефон: {context.user_data['phone']}\n"
        f"📍 Город: {context.user_data['city']}\n"
        f"💬 Telegram: {telegram_user}\n\n"
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
        )

    except Exception:
        logger.exception(
            "Не удалось отправить уведомление администратору"
        )


    # ==================================================
    # ФИНАЛЬНОЕ СООБЩЕНИЕ + КНОПКА ДОПОЛНЕНИЯ
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
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    text = update.message.text.strip()

    # Если нажата кнопка
    if text == "➕ Добавить к запросу":

        await update.message.reply_text(
            "Укажите дополнительные запчасти "
            "или напишите комментарий:",
            reply_markup=ReplyKeyboardRemove(),
        )

        context.user_data["waiting_addition"] = True

        return ADD_MORE


    # Если ждём текст дополнения
    if context.user_data.get("waiting_addition"):

        addition = text

        row = context.user_data.get("sheet_row")

        try:
            if row:

                # Столбец H = Запчасти
                current_parts = sheet.cell(row, 8).value or ""

                new_parts = (
                    current_parts
                    + "\n"
                    + "Дополнение: "
                    + addition
                )

                sheet.update_cell(
                    row,
                    8,
                    new_parts
                )

                logger.info(
                    "Дополнение добавлено в Google Sheets"
                )

        except Exception:

            logger.exception(
                "Ошибка добавления дополнения в Google Sheets"
            )


        # Уведомление администратору
        admin_add_message = (
            "📝 ДОПОЛНЕНИЕ К ЗАПРОСУ\n\n"
            f"👤 Клиент: {context.user_data.get('client', '')}\n"
            f"📞 Телефон: {context.user_data.get('phone', '')}\n"
            f"📍 Город: {context.user_data.get('city', '')}\n"
            f"🔢 VIN: {context.user_data.get('vin', '')}\n\n"
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
                "Не удалось отправить дополнение администратору"
            )


        # Кнопку оставляем, чтобы можно было добавить ещё
        add_keyboard = ReplyKeyboardMarkup(
            [
                ["➕ Добавить к запросу"]
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
        )

        await update.message.reply_text(
            "Спасибо! Дополнение к Вашему запросу отправлено.\n\n"
            "Если хотите добавить ещё что-нибудь, "
            "нажмите кнопку «➕ Добавить к запросу».",
            reply_markup=add_keyboard,
        )

        context.user_data["waiting_addition"] = False

        return ADD_MORE


    return ADD_MORE


# ==================================================
# /CANCEL
# ==================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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
# ЗАПУСК
# ==================================================

def main():

    start_health_server()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    conversation_handler = ConversationHandler(

        entry_points=[
            CommandHandler(
                "start",
                start,
            )
        ],

        states={

            MARK: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_mark,
                )
            ],

            MODEL: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_model,
                )
            ],

            YEAR: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_year,
                )
            ],

            ENGINE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_engine,
                )
            ],

            FUEL: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_fuel,
                )
            ],

            VIN: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_vin,
                )
            ],

            PARTS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
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
                    filters.TEXT & ~filters.COMMAND,
                    get_client,
                )
            ],

            CITY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    get_city,
                )
            ],

            ADD_MORE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
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
    )

    application.add_handler(
        conversation_handler
    )

    logger.info(
        "AutoPartsBot запущен"
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()

import os
import logging
import datetime
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

# Файл добавлен в Render -> Secret Files
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
# ПРОВЕРКА TELEGRAM TOKEN
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
) = range(10)


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

    # Здесь ТОЛЬКО сохраняем запчасти.
    # Заявка ещё НЕ отправляется.
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

    context.user_data["phone"] = phone

    # После телефона обязательно спрашиваем имя клиента
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

    # Telegram пользователя сохраняем отдельно для логов
    if user.username:
        telegram_user = f"@{user.username}"
    else:
        telegram_user = user.full_name or str(user.id)

    date = datetime.datetime.now().strftime(
        "%d.%m.%Y %H:%M"
    )

    # --------------------------------------------------
    # ПОРЯДОК СТОЛБЦОВ В GOOGLE SHEETS:
    #
    # Дата
    # Марка
    # Модель
    # Год
    # Двигатель
    # Топливо
    # VIN
    # Запчасти
    # Телефон
    # Клиент
    # Город
    # --------------------------------------------------

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

    # ==================================================
    # 1. ЗАПИСЬ В GOOGLE SHEETS
    # ==================================================

    try:

        sheet.append_row(
            data,
            value_input_option="USER_ENTERED",
        )

        logger.info(
            "Новый запрос записан в Google Sheets"
        )

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
    # 2. УВЕДОМЛЕНИЕ АДМИНИСТРАТОРУ
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

        logger.info(
            "Уведомление администратору отправлено"
        )

    except Exception:

        # ВАЖНО:
        # Если уведомление админу не отправилось,
        # заявка уже сохранена в таблице.
        # Клиент всё равно получает подтверждение.
        logger.exception(
            "Не удалось отправить уведомление администратору"
        )


    # ==================================================
    # 3. ФИНАЛЬНЫЙ ОТВЕТ КЛИЕНТУ
    # ==================================================

    await update.message.reply_text(
        "Спасибо! Ваш запрос отправлен. "
        "Мы свяжемся с Вами в ближайшее время.\n\n"
        "Если хотите отправить запрос снова, "
        "используйте команду /start.",
        reply_markup=ReplyKeyboardRemove(),
    )

    logger.info(
        "Запрос полностью обработан"
    )

    context.user_data.clear()

    return ConversationHandler.END


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

    # HTTP endpoint для Render / UptimeRobot
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

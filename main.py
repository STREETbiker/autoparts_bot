import os
import json
import logging
import datetime

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


# --------------------------------------------------
# НАСТРОЙКИ
# --------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")

SHEET_ID = "19klP5Uw-_gLe8LS9N5-dzs_53qhAucQisACPMGLbpzs"
WORKSHEET_NAME = "Запросы"

# Твой Telegram ID для уведомлений
ADMIN_CHAT_ID = 1112183569


# --------------------------------------------------
# ЛОГИ
# --------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------
# ПРОВЕРКА ПЕРЕМЕННЫХ
# --------------------------------------------------

if not BOT_TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN")

if not GOOGLE_CREDS_JSON:
    raise RuntimeError("Не задана переменная окружения GOOGLE_CREDS_JSON")


# --------------------------------------------------
# GOOGLE SHEETS
# --------------------------------------------------

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

creds_dict = json.loads(GOOGLE_CREDS_JSON)

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    creds_dict,
    scope,
)

client = gspread.authorize(creds)

sheet = client.open_by_key(
    SHEET_ID
).worksheet(WORKSHEET_NAME)


# --------------------------------------------------
# СОСТОЯНИЯ ДИАЛОГА
# --------------------------------------------------

(
    MARK,
    MODEL,
    YEAR,
    ENGINE,
    FUEL,
    VIN,
    PARTS,
    PHONE,
) = range(8)


# --------------------------------------------------
# START
# --------------------------------------------------

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    await update.message.reply_text(
        "Приветствуем!\n\n"
        "Укажите марку автомобиля:",
        reply_markup=ReplyKeyboardRemove(),
    )

    return MARK


# --------------------------------------------------
# МАРКА
# --------------------------------------------------

async def get_mark(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["mark"] = update.message.text.strip()

    await update.message.reply_text(
        "Введите модель автомобиля:"
    )

    return MODEL


# --------------------------------------------------
# МОДЕЛЬ
# --------------------------------------------------

async def get_model(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["model"] = update.message.text.strip()

    await update.message.reply_text(
        "Введите год выпуска:"
    )

    return YEAR


# --------------------------------------------------
# ГОД
# --------------------------------------------------

async def get_year(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["year"] = update.message.text.strip()

    await update.message.reply_text(
        "Введите объём двигателя (например, 1.6):"
    )

    return ENGINE


# --------------------------------------------------
# ДВИГАТЕЛЬ
# --------------------------------------------------

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


# --------------------------------------------------
# ТОПЛИВО
# --------------------------------------------------

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


# --------------------------------------------------
# VIN
# --------------------------------------------------

async def get_vin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["vin"] = update.message.text.strip().upper()

    await update.message.reply_text(
        "Какие запчасти вас интересуют?\n\n"
        "Укажите названия и артикулы, если они вам известны:"
    )

    return PARTS


# --------------------------------------------------
# ЗАПЧАСТИ
# --------------------------------------------------

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
        "Укажите контактный номер телефона.\n\n"
        "Можно ввести номер вручную или нажать кнопку ниже:",
        reply_markup=phone_keyboard,
    )

    return PHONE


# --------------------------------------------------
# ТЕЛЕФОН
# --------------------------------------------------

async def get_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()

    context.user_data["phone"] = phone

    user = update.effective_user

    if user.username:
        username = f"@{user.username}"
    else:
        username = user.full_name

    date = datetime.datetime.now().strftime(
        "%d.%m.%Y %H:%M"
    )

    data = [
        date,
        username,
        context.user_data["mark"],
        context.user_data["model"],
        context.user_data["year"],
        context.user_data["engine"],
        context.user_data["fuel"],
        context.user_data["vin"],
        context.user_data["parts"],
        context.user_data["phone"],
    ]

    try:
        # Запись в Google Sheets
        sheet.append_row(
            data,
            value_input_option="USER_ENTERED",
        )

        # Уведомление администратору
        admin_message = (
            "🔔 НОВЫЙ ЗАПРОС\n\n"
            f"👤 Клиент: {username}\n"
            f"📞 Телефон: {phone}\n\n"
            f"🚗 Автомобиль: "
            f"{context.user_data['mark']} "
            f"{context.user_data['model']}\n"
            f"📅 Год: {context.user_data['year']}\n"
            f"⚙️ Двигатель: {context.user_data['engine']}\n"
            f"⛽ Топливо: {context.user_data['fuel']}\n"
            f"🔢 VIN: {context.user_data['vin']}\n\n"
            f"🔧 Запчасти:\n"
            f"{context.user_data['parts']}"
        )

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
        )

        await update.message.reply_text(
            "Спасибо! Ваш запрос отправлен.\n\n"
            "Мы свяжемся с вами в ближайшее время.\n\n"
            "Если хотите отправить новый запрос, "
            "используйте команду /start.",
            reply_markup=ReplyKeyboardRemove(),
        )

    except Exception:
        logger.exception(
            "Ошибка при обработке запроса"
        )

        await update.message.reply_text(
            "Произошла ошибка при отправке запроса.\n"
            "Попробуйте ещё раз немного позже.",
            reply_markup=ReplyKeyboardRemove(),
        )

    context.user_data.clear()

    return ConversationHandler.END


# --------------------------------------------------
# CANCEL
# --------------------------------------------------

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data.clear()

    await update.message.reply_text(
        "Запрос отменён.\n"
        "Чтобы начать заново, используйте /start.",
        reply_markup=ReplyKeyboardRemove(),
    )

    return ConversationHandler.END


# --------------------------------------------------
# ЗАПУСК БОТА
# --------------------------------------------------

def main():

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    conversation_handler = ConversationHandler(

        entry_points=[
            CommandHandler("start", start)
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
                        | (filters.TEXT & ~filters.COMMAND)
                    ),
                    get_phone,
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

    logger.info("✅ AutoPartsBot запущен")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()

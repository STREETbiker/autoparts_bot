import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, filters, ContextTypes
)

(MARK, MODEL, YEAR, ENGINE, FUEL, VIN, PARTS) = range(7)

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open_by_key("19klP5Uw-_gLe8LS9N5-dzs_53qhAucQisACPMGLbpzs").worksheet("Запросы")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Укажите марку автомобиля:")
    return MARK

async def get_mark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['mark'] = update.message.text
    await update.message.reply_text("Введите модель:")
    return MODEL

async def get_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['model'] = update.message.text
    await update.message.reply_text("Введите год выпуска:")
    return YEAR

async def get_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['year'] = update.message.text
    await update.message.reply_text("Введите объём двигателя (например, 1.6):")
    return ENGINE

async def get_engine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['engine'] = update.message.text
    keyboard = [["Бензин", "Дизель"]]
    await update.message.reply_text(
        "Выберите тип топлива:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return FUEL

async def get_fuel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['fuel'] = update.message.text
    await update.message.reply_text("Введите VIN автомобиля:", reply_markup=ReplyKeyboardRemove())
    return VIN

async def get_vin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['vin'] = update.message.text
    await update.message.reply_text("Какие запчасти вас интересуют? Укажите названия, артикулы (если знаете):")
    return PARTS

async def get_parts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['parts'] = update.message.text

    username = update.effective_user.username or update.effective_user.first_name
    date = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

    data = [
        date,
        f"@{username}",
        context.user_data['mark'],
        context.user_data['model'],
        context.user_data['year'],
        context.user_data['engine'],
        context.user_data['fuel'],
        context.user_data['vin'],
        context.user_data['parts']
    ]

    sheet.append_row(data)
    await update.message.reply_text("Спасибо! Ваш запрос отправлен. Мы свяжемся с вами в ближайшее время.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Запрос отменён.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

app = Application.builder().token("8192798090:AAFwYArtBKFtZTiwCzpkrRkbH5MCWDCpoRo").build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        MARK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_mark)],
        MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_model)],
        YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_year)],
        ENGINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_engine)],
        FUEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fuel)],
        VIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_vin)],
        PARTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_parts)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

app.add_handler(conv_handler)

app.run_polling()



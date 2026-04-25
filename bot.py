import logging
import requests
import cloudinary
import cloudinary.uploader
import json
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

load_dotenv() 

TOKEN = os.getenv("BOT_TOKEN")
APPS_SCRIPT_URL = os.getenv("APPS_SCRIPT_URL")
WEB_APP_URL = "https://itkulovfv.github.io/helper_bot/"

cloudinary.config(secure=True)

ALLOWED_USERS = [int(i) for i in os.getenv("ALLOWED_USERS", "").split(",") if i]

# Настройка логов
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return

    keyboard = [[InlineKeyboardButton("🚀 Открыть панель управления", web_app=WebAppInfo(url=WEB_APP_URL))]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Привет, {update.effective_user.first_name}! 👋\nИспользуй кнопку ниже, чтобы управлять результатами:",
        reply_markup=reply_markup
    )

async def handle_webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает сигналы от Mini App (кнопки в интерфейсе)"""
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        action = data.get('action')
        target = data.get('target')

        if action == 'upload':
            context.user_data['target_sheet'] = target
            await update.message.reply_text(f"📥 Окей, жду фото для раздела: {target}\nПросто пришли его следующим сообщением!")

            
    except Exception as e:
        logging.error(f"Ошибка WebApp Data: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Загружает присланное фото в облако и таблицу"""
    target = context.user_data.get('target_sheet')
    
    if not target:
        await update.message.reply_text("❌ Сначала выбери раздел в панели управления!")
        return

    status_msg = await update.message.reply_text("⏳ Загружаю фото...")

    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytearray = await photo_file.download_as_bytearray()

        upload = cloudinary.uploader.upload(bytes(photo_bytearray))
        img_url = upload['secure_url']

        payload = {"url": img_url, "target_sheet": target}
        requests.post(APPS_SCRIPT_URL, json=payload, timeout=15)
        
        await status_msg.edit_text(f"🚀 Успешно добавлено в {target}!")
        context.user_data['target_sheet'] = None
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка при загрузке: {e}")

# --- 3. ЗАПУСК БОТА ---

if __name__ == '__main__':
    from telegram.request import HTTPXRequest
    
    request = HTTPXRequest(connect_timeout=20, read_timeout=20)
    app = ApplicationBuilder().token(TOKEN).request(request).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("✅ Бот успешно запущен и готов к работе!")
    app.run_polling()
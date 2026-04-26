import os
import logging
import io
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import WebAppInfo
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

# Загрузка настроек
load_dotenv()

# Настройки из .env
API_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS = [int(i.strip()) for i in os.getenv("ALLOWED_USERS", "").split(",") if i.strip()]
GOOGLE_URL = "https://script.google.com/macros/s/AKfycbxaUlAyQ_7CwoDlMmxcKSUxrTWdIonUpQBlmZiF31XR3XRLdu0YEigQ8yz_xZCAGp0fMw/exec"
GITHUB_URL = "https://itkulovfv.github.io/helper_bot/"

# Конфигурация Cloudinary
cloudinary.config(
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"), 
    api_key = os.getenv("CLOUDINARY_API_KEY"), 
    api_secret = os.getenv("CLOUDINARY_API_SECRET"),
    secure = True
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return # Молча игнорируем посторонних

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Открыть Freedom Air", web_app=WebAppInfo(url=GITHUB_URL)))
    
    await message.answer(
        f"Привет, {message.from_user.first_name}! 🦅\nСистема Freedom Air готова к работе. Пришли фото для эфира.",
        reply_markup=markup
    )

@dp.message_handler(content_types=['photo'])
async def handle_photo(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        return

    status = await message.answer("⏳ Загрузка в облако...")

    try:
        # 1. Получаем инфо о фото
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        
        # 2. Скачиваем файл в оперативную память (Безопасно!)
        downloaded_file = await bot.download_file(file_info.file_path)
        image_stream = io.BytesIO(downloaded_file.read())

        # 3. Загружаем в Cloudinary напрямую из памяти
        upload_result = cloudinary.uploader.upload(image_stream, folder="tg_onair")
        secure_url = upload_result.get("secure_url")

        # 4. Отправляем данные в Google Таблицу
        requests.post(GOOGLE_URL, json={
            "action": "add_row",
            "user_id": message.from_user.id,
            "image_url": secure_url,
            "user_name": message.from_user.full_name
        })

        await status.edit_text(f"✅ Фото добавлено!\nURL: {secure_url}")

    except Exception as e:
        logging.error(f"Error: {e}")
        await status.edit_text("❌ Ошибка при обработке фото.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
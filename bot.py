import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import WebAppInfo
from dotenv import load_dotenv

# 1. Загрузка переменных окружения
load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
# Список ID через запятую из .env
ALLOWED_USERS = [int(i.strip()) for i in os.getenv("ALLOWED_USERS", "").split(",") if i.strip()]

# Твоя ссылка на GitHub Pages, где лежит index.html
WEB_APP_URL = "https://github.com/itkulovfv/helper_bot"

# 2. Настройка логирования и инициализация
logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    user_id = message.from_user.id
    
    # ПРОВЕРКА: Пускаем только своих
    if user_id not in ALLOWED_USERS:
        logging.warning(f"Попытка доступа: ID {user_id} отклонен.")
        await message.answer("⛔️ Доступ ограничен. Вы не в списке Freedom On Air.")
        return

    # Создаем кнопку для открытия Mini App
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        text="🦅 Открыть Freedom On Air", 
        web_app=WebAppInfo(url=WEB_APP_URL)
    ))

    await message.answer(
        f"Добро пожаловать, {message.from_user.first_name}!\n\n"
        "Ваш доступ подтвержден. Нажмите на кнопку ниже, чтобы войти в панель управления эфиром.",
        reply_markup=markup
    )

if __name__ == '__main__':
    # Запуск бота
    executor.start_polling(dp, skip_updates=True)
import os
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from dotenv import load_dotenv

load_dotenv()

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher(bot)
ALLOWED_USERS_RAW = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = [int(i.strip()) for i in ALLOWED_USERS_RAW.split(",") if i.strip()]

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    if message.from_user.id not in ALLOWED_USERS:
        await message.answer("Доступ запрещен.")
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        text="Freedom On Air", 
        web_app=types.WebAppInfo(url=os.getenv("WEB_APP_URL"))
    ))
    
    await message.answer("Панель управления активна:", reply_markup=markup)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
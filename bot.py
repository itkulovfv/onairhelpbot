import os
import json
import hmac
import hashlib
import logging
import asyncio
from urllib.parse import parse_qs

import aiohttp
from aiohttp import web
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "").strip()
GOOGLE_SCRIPT_URL = os.getenv("GOOGLE_SCRIPT_URL", "").strip()
MINI_APP_URL = os.getenv("MINI_APP_URL", "").strip()
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8080"))
ALLOWED_USER_IDS_RAW = os.getenv("ALLOWED_USER_IDS", "").strip()

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# Проверка наличия переменных при запуске
def check_env():
    missing = []
    if not BOT_TOKEN: missing.append("BOT_TOKEN")
    if not IMGBB_API_KEY: missing.append("IMGBB_API_KEY")
    if not GOOGLE_SCRIPT_URL: missing.append("GOOGLE_SCRIPT_URL")
    if not MINI_APP_URL: missing.append("MINI_APP_URL")
    if not ALLOWED_USER_IDS_RAW: missing.append("ALLOWED_USER_IDS")
    
    if missing:
        log.error(f"❌ ОТСУТСТВУЮТ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ: {', '.join(missing)}")
        log.error("Убедитесь, что вы добавили их во вкладку Variables в Railway!")
        return False
    return True

ALLOWED_USER_IDS = set(
    int(uid.strip()) for uid in ALLOWED_USER_IDS_RAW.split(",") if uid.strip()
)


# ─── Telegram initData validation ─────────────────────────────────────────────
def validate_init_data(init_data_raw: str) -> dict | None:
    """Validate Telegram Web App initData. Returns user dict or None."""
    try:
        parsed = parse_qs(init_data_raw)
        received_hash = parsed.get("hash", [None])[0]
        if not received_hash:
            return None

        # Build data-check-string (sorted, without hash)
        items = []
        for key, vals in parsed.items():
            if key != "hash":
                items.append(f"{key}={vals[0]}")
        items.sort()
        data_check_string = "\n".join(items)

        # HMAC validation
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed, received_hash):
            return None

        user_data = parsed.get("user", [None])[0]
        if user_data:
            return json.loads(user_data)
        return None
    except Exception as e:
        log.error(f"initData validation error: {e}")
        return None


def authorize_request(init_data_raw: str) -> tuple[dict | None, str | None]:
    """Validate initData and check whitelist. Returns (user, error_msg)."""
    if not init_data_raw:
        return None, "Missing initData"
    user = validate_init_data(init_data_raw)
    if not user:
        return None, "Invalid initData signature"
    if user.get("id") not in ALLOWED_USER_IDS:
        return None, "User not authorized"
    return user, None


# ─── API Handlers ─────────────────────────────────────────────────────────────
async def handle_get_photos(request: web.Request) -> web.Response:
    """GET /api/photos?section=investor — get photos for a section."""
    section = request.query.get("section", "")
    if section not in ("investor", "trader"):
        return web.json_response({"error": "Invalid section"}, status=400)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{GOOGLE_SCRIPT_URL}?action=list&section={section}") as resp:
                data = await resp.json(content_type=None)
        return web.json_response(data)
    except Exception as e:
        log.error(f"Get photos error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_upload(request: web.Request) -> web.Response:
    """POST /api/upload — upload photos to ImgBB and save to Google Sheet."""
    try:
        reader = await request.multipart()
        init_data = ""
        section = ""
        files = []

        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "initData":
                init_data = (await part.read()).decode()
            elif part.name == "section":
                section = (await part.read()).decode()
            elif part.name == "photos":
                file_data = await part.read()
                files.append({"data": file_data, "filename": part.filename or "photo.jpg"})

        # Auth
        user, err = authorize_request(init_data)
        if err:
            return web.json_response({"error": err}, status=403)

        if section not in ("investor", "trader"):
            return web.json_response({"error": "Invalid section"}, status=400)
        if not files or len(files) != 3:
            return web.json_response({"error": "Exactly 3 photos required"}, status=400)

        # Upload each photo to ImgBB
        uploaded = []
        async with aiohttp.ClientSession() as session:
            for f in files:
                import base64
                b64 = base64.b64encode(f["data"]).decode()
                form = aiohttp.FormData()
                form.add_field("key", IMGBB_API_KEY)
                form.add_field("image", b64)
                form.add_field("name", f["filename"])

                async with session.post("https://api.imgbb.com/1/upload", data=form) as resp:
                    result = await resp.json()
                    if not result.get("success"):
                        return web.json_response({"error": f"ImgBB error: {result}"}, status=500)
                    uploaded.append({
                        "url": result["data"]["url"],
                        "thumb": result["data"].get("thumb", {}).get("url", result["data"]["url"]),
                        "filename": f["filename"],
                    })

            # Save to Google Sheet
            payload = {
                "action": "add",
                "section": section,
                "photos": uploaded,
                "userId": str(user.get("id", "")),
                "userName": user.get("first_name", ""),
            }
            async with session.post(GOOGLE_SCRIPT_URL, json=payload) as resp:
                gs_result = await resp.json(content_type=None)

        log.info(f"User {user.get('id')} uploaded {len(uploaded)} photos to {section}")
        return web.json_response({"status": "ok", "photos": uploaded})

    except Exception as e:
        log.error(f"Upload error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_delete(request: web.Request) -> web.Response:
    """POST /api/delete — delete selected photos."""
    try:
        data = await request.json()
        init_data = data.get("initData", "")
        section = data.get("section", "")
        row_ids = data.get("rowIds", [])

        user, err = authorize_request(init_data)
        if err:
            return web.json_response({"error": err}, status=403)

        if section not in ("investor", "trader"):
            return web.json_response({"error": "Invalid section"}, status=400)
        if not row_ids:
            return web.json_response({"error": "No photos selected"}, status=400)

        async with aiohttp.ClientSession() as session:
            payload = {"action": "delete", "section": section, "rowIds": row_ids}
            async with session.post(GOOGLE_SCRIPT_URL, json=payload) as resp:
                gs_result = await resp.json(content_type=None)

        log.info(f"User {user.get('id')} deleted rows {row_ids} from {section}")
        return web.json_response({"status": "ok"})

    except Exception as e:
        log.error(f"Delete error: {e}")
        return web.json_response({"error": str(e)}, status=500)


# ─── CORS middleware ──────────────────────────────────────────────────────────
@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            resp = e
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


# ─── Telegram Bot Handlers ────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔ Доступ запрещён. Обратитесь к администратору.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Управление фото", web_app=WebAppInfo(url=MINI_APP_URL))]
    ])
    await update.message.reply_text(
        f"👋 Привет, *{user.first_name}*!\n\n"
        "Нажми кнопку ниже, чтобы открыть панель управления фотографиями на сайте:",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ALLOWED_USER_IDS:
        return
    await update.message.reply_text(
        "📖 *Инструкция*\n\n"
        "1. Нажмите кнопку «📸 Управление фото»\n"
        "2. Выберите раздел (Инвестор / Трейдер)\n"
        "3. Просматривайте, добавляйте или удаляйте фото\n\n"
        "📌 Загрузка — ровно 3 фото за раз\n"
        "📌 Удаление — выберите ненужные фото и удалите",
        parse_mode="Markdown",
    )


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ваш Telegram ID: `{update.effective_user.id}`", parse_mode="Markdown")


async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and user.id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔ Доступ запрещён.")


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    if not check_env():
        return
    # Telegram bot
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", cmd_start))
    bot_app.add_handler(CommandHandler("help", cmd_help))
    bot_app.add_handler(CommandHandler("myid", cmd_myid))
    bot_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, fallback))

    # HTTP API server
    web_app = web.Application(middlewares=[cors_middleware])
    web_app.router.add_get("/api/photos", handle_get_photos)
    web_app.router.add_post("/api/upload", handle_upload)
    web_app.router.add_post("/api/delete", handle_delete)
    web_app.router.add_route("OPTIONS", "/api/{tail:.*}", lambda r: web.Response())

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, SERVER_HOST, SERVER_PORT)

    log.info(f"Authorized users: {ALLOWED_USER_IDS}")
    log.info(f"API server starting on {SERVER_HOST}:{SERVER_PORT}")

    # HTTP API server runner
    web_app = web.Application(middlewares=[cors_middleware])
    web_app.router.add_get("/api/photos", handle_get_photos)
    web_app.router.add_post("/api/upload", handle_upload)
    web_app.router.add_post("/api/delete", handle_delete)
    web_app.router.add_route("OPTIONS", "/api/{tail:.*}", lambda r: web.Response())

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, SERVER_HOST, SERVER_PORT)
    await site.start()

    # Start Telegram bot (blocking call)
    # run_polling internally calls initialize(), start() and blocks until stop
    await bot_app.run_polling(allowed_updates=Update.ALL_TYPES)
    
    # Cleanup after bot stops
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

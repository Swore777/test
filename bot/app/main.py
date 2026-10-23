"""Telegram-бот каталога (aiogram 3).

Бот stateless: никакого FSM и состояния в памяти — товар создаётся одним сообщением
(фото + подпись), поэтому любой инстанс может обработать любой апдейт.
Для нескольких инстансов используется webhook (BOT_MODE=webhook): nginx балансирует
запросы Telegram между репликами. Polling (BOT_MODE=polling) — только для локальной
отладки в одном экземпляре: Telegram не даёт двум клиентам одновременно делать getUpdates.
"""
import asyncio
import hashlib
import io
import logging
import os
import random

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}
WEBAPP_URL = os.environ["WEBAPP_URL"]  # https://.../ — каталог Next.js
BACKEND_URL = os.environ.get("BACKEND_URL", "http://nginx").rstrip("/")
ADMIN_API_TOKEN = os.environ["ADMIN_API_TOKEN"]
BOT_MODE = os.environ.get("BOT_MODE", "webhook")
WEBHOOK_BASE = os.environ.get("WEBHOOK_BASE", "").rstrip("/")  # https://домен
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/tg/webhook")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

CREATE_BTN = "Создать товар"

router = Router()


def is_admin(message: Message) -> bool:
    return message.from_user is not None and message.from_user.id in ADMIN_IDS


def catalog_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть каталог", web_app=WebAppInfo(url=WEBAPP_URL))]]
    )


def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=CREATE_BTN)]], resize_keyboard=True)


async def greet(message: Message) -> None:
    await message.answer("У меня есть товар", reply_markup=catalog_markup())
    if is_admin(message):
        await message.answer(
            f"Вы администратор. Чтобы добавить товар, нажмите «{CREATE_BTN}».",
            reply_markup=admin_keyboard(),
        )


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    await greet(message)


@router.message(F.text == CREATE_BTN)
async def on_create(message: Message) -> None:
    if not is_admin(message):
        await message.answer("Добавлять товары может только администратор.")
        return
    await message.answer("Пришлите одним сообщением фото товара с названием в подписи.")


@router.message(F.photo)
async def on_photo(message: Message, bot: Bot) -> None:
    if not is_admin(message):
        await greet(message)
        return
    title = (message.caption or "").strip()
    if not title:
        await message.answer("Нужна подпись к фото — это название товара. Пришлите фото ещё раз с подписью.")
        return

    photo = message.photo[-1]  # самое большое разрешение
    buf = io.BytesIO()
    await bot.download(photo, destination=buf)

    form = aiohttp.FormData()
    form.add_field("title", title)
    form.add_field("image", buf.getvalue(), filename=f"{photo.file_unique_id}.jpg", content_type="image/jpeg")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BACKEND_URL}/api/products",
                data=form,
                headers={"Authorization": f"Bearer {ADMIN_API_TOKEN}"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 201:
                    raise RuntimeError(f"backend {resp.status}: {await resp.text()}")
                product = await resp.json()
    except Exception:
        logging.exception("create product failed")
        await message.answer("Не удалось сохранить товар, попробуйте ещё раз.")
        return
    await message.answer(f"Товар «{product['title']}» добавлен (#{product['id']}).", reply_markup=catalog_markup())


@router.message()
async def on_any(message: Message) -> None:
    await greet(message)


def build() -> tuple[Bot, Dispatcher]:
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    return bot, dp


def run_webhook() -> None:
    bot, dp = build()

    async def on_startup(bot: Bot) -> None:
        # Все реплики ставят один и тот же webhook. При одновременном старте Telegram отвечает
        # части из них 429 (flood control), поэтому: уже стоит нужный — не трогаем, иначе
        # повторяем после паузы. Секрет getWebhookInfo не показывает, поэтому его отпечаток
        # лежит в query-параметре URL: смена секрета меняет URL и webhook переставится.
        tag = hashlib.sha256(WEBHOOK_SECRET.encode()).hexdigest()[:12]
        url = f"{WEBHOOK_BASE}{WEBHOOK_PATH}?v={tag}"
        updates = dp.resolve_used_update_types()
        for attempt in range(10):
            try:
                info = await bot.get_webhook_info()
                if info.url == url and set(info.allowed_updates or []) == set(updates):
                    return
                await bot.set_webhook(url, secret_token=WEBHOOK_SECRET or None, allowed_updates=updates)
                return
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + random.random() * (attempt + 1))

    dp.startup.register(on_startup)
    app = web.Application()
    app.router.add_get("/health", lambda _: web.json_response({"status": "ok"}))
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET or None).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=8080)


async def run_polling() -> None:
    bot, dp = build()
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if BOT_MODE == "polling":
        asyncio.run(run_polling())
    else:
        run_webhook()

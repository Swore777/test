# test-catalog

Каталог товаров с ботом и Telegram Mini App (тестовое).

Демо: https://catalog.193-168-49-200.sslip.io/
Бот: [@testovoe12345_bot](https://t.me/testovoe12345_bot)

Стек: Next.js (App Router), FastAPI, aiogram 3, PostgreSQL, MinIO. Всё в docker compose, снаружи торчит только nginx.

## Запуск

```bash
cp .env.example .env
docker compose up -d --build
```

В `.env` надо вписать токен бота, свой telegram id в `ADMIN_IDS` и `PUBLIC_URL`. Адрес должен быть https, иначе Telegram не откроет Mini App и не примет webhook. HTTPS compose сам не делает, у меня перед ним стоит Traefik.

Локально без домена можно запустить бота через polling: `BOT_MODE=polling`, `BOT_REPLICAS=1`.

Добавить товар без бота:

```bash
curl -H "Authorization: Bearer $ADMIN_API_TOKEN" -F title=Чайник -F image=@kettle.jpg http://localhost:8080/api/products
```

## Что где

`frontend` — страница «Каталог» со списком товаров. Внутри Telegram открывается как Mini App: кнопкой под сообщением бота или из меню.

`backend` — `GET /api/products` отдаёт список, `POST /api/products` создаёт товар (нужен `ADMIN_API_TOKEN`). Картинка кладётся в MinIO, запись в Postgres.

`bot` — на любое сообщение отвечает «У меня есть товар» и кнопкой каталога. Админу показывает ещё «Создать товар»: шлёшь фото с названием в подписи, бот отправляет его в API.

`nginx` — `/` во frontend, `/api/` в backend, `/tg/` в бота, `/media/` в MinIO на чтение.

## Несколько инстансов

backend, frontend и bot по умолчанию запущены по две копии, можно больше:

```bash
docker compose up -d --scale backend=3 --scale frontend=3 --scale bot=3
```

Состояния в сервисах нет, всё лежит в Postgres и MinIO. Бот без FSM, товар приходит одним сообщением, так что любая копия может его обработать. Бот работает через webhook, потому что при polling две копии конфликтуют на getUpdates.

Пара мест, где пришлось повозиться:

- при одновременном старте ботов Telegram отвечал части из них 429 на setWebhook, и они падали. Теперь бот сначала смотрит getWebhookInfo и ставит webhook, только если он другой, а на 429 ждёт и повторяет;
- таблицу и бакет создаёт backend при старте, под `pg_advisory_xact_lock`, чтобы реплики не делали это одновременно;
- nginx с `resolve` в upstream (есть с 1.27.3) видит новые реплики после `--scale` без перезапуска.

Проверял так: гасил по одной копии backend и frontend, сайт и API продолжали отвечать. После `--scale backend=3` запросы расходились по всем трём.

MinIO взят из `chainguard/minio`, потому что официальный образ с Docker Hub больше не тянется.

import asyncio
import io
import json
import os
import uuid
from contextlib import asynccontextmanager

import asyncpg
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from minio import Minio

DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_API_TOKEN = os.environ["ADMIN_API_TOKEN"]
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "minio:9000")
S3_ACCESS_KEY = os.environ["S3_ACCESS_KEY"]
S3_SECRET_KEY = os.environ["S3_SECRET_KEY"]
S3_BUCKET = os.environ.get("S3_BUCKET", "products")
S3_SECURE = os.environ.get("S3_SECURE", "false").lower() == "true"
# Публичный префикс, по которому nginx отдаёт объекты бакета (см. nginx.conf: /media/ -> minio).
PUBLIC_MEDIA_BASE = os.environ.get("PUBLIC_MEDIA_BASE", "/media").rstrip("/")
MAX_IMAGE_BYTES = 10 * 1024 * 1024

MIGRATION = """
CREATE TABLE IF NOT EXISTS products (
    id         BIGSERIAL PRIMARY KEY,
    title      TEXT        NOT NULL,
    image_key  TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

s3 = Minio(S3_ENDPOINT, access_key=S3_ACCESS_KEY, secret_key=S3_SECRET_KEY, secure=S3_SECURE)

# Анонимное чтение объектов бакета: картинки отдаются браузеру через nginx /media/.
PUBLIC_READ_POLICY = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"AWS": ["*"]},
        "Action": ["s3:GetObject"],
        "Resource": [f"arn:aws:s3:::{S3_BUCKET}/*"],
    }],
})


def ensure_bucket() -> None:
    if not s3.bucket_exists(S3_BUCKET):
        s3.make_bucket(S3_BUCKET)
    s3.set_bucket_policy(S3_BUCKET, PUBLIC_READ_POLICY)


async def retry(fn, attempts: int = 30):
    """Зависимости (Postgres, MinIO) могут подниматься дольше API — ждём, а не падаем."""
    for i in range(attempts):
        try:
            return await fn()
        except Exception:
            if i == attempts - 1:
                raise
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await retry(lambda: asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10))

    # Несколько инстансов стартуют одновременно: инициализацию (схема БД, бакет)
    # сериализуем advisory-локом; все шаги идемпотентны.
    async def init():
        async with app.state.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(4242)")
                await conn.execute(MIGRATION)
                await run_in_threadpool(ensure_bucket)

    await retry(init)
    yield
    await app.state.pool.close()


app = FastAPI(title="Catalog API", lifespan=lifespan)


def require_admin(authorization: str = Header(default="")) -> None:
    if authorization != f"Bearer {ADMIN_API_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def to_dto(row: asyncpg.Record) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "image_url": f"{PUBLIC_MEDIA_BASE}/{S3_BUCKET}/{row['image_key']}",
        "created_at": row["created_at"].isoformat(),
    }


@app.get("/api/health")
async def health():
    async with app.state.pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok", "instance": os.environ.get("HOSTNAME", "")}


@app.get("/api/products")
async def list_products():
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, image_key, created_at FROM products ORDER BY id DESC"
        )
    return [to_dto(r) for r in rows]


@app.post("/api/products", status_code=201, dependencies=[Depends(require_admin)])
async def create_product(title: str = Form(...), image: UploadFile = File(...)):
    title = title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="title is empty")
    content_type = image.content_type or "application/octet-stream"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="file is not an image")
    data = await image.read()
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="image is empty or too large")

    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(content_type, "bin")
    key = f"{uuid.uuid4().hex}.{ext}"
    await run_in_threadpool(
        s3.put_object, S3_BUCKET, key, io.BytesIO(data), len(data), content_type=content_type
    )
    try:
        async with app.state.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO products (title, image_key) VALUES ($1, $2)"
                " RETURNING id, title, image_key, created_at",
                title,
                key,
            )
    except Exception:
        # Не оставляем в бакете файл без записи в БД.
        await run_in_threadpool(s3.remove_object, S3_BUCKET, key)
        raise
    return to_dto(row)

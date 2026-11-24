import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import SessionLocal, init_db
from .routers import auth, issues, official, public

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("civicmind")

settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.SEED_DEMO:
        from .seed import seed_demo
        with SessionLocal() as db:
            seed_demo(db)
    if settings.SECRET_KEY.startswith("dev-only-secret"):
        log.warning("SECRET_KEY is the built-in development value. Set a long random SECRET_KEY before going live.")
    log.info("Civic Mind ready - OTP mode: %s, AI: %s", settings.OTP_MODE, "claude+local" if settings.ANTHROPIC_API_KEY else "local")
    yield


app = FastAPI(title="Civic Mind", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


for r in (auth.router, public.router, issues.router, official.router):
    app.include_router(r)

app.mount("/media", StaticFiles(directory=str(settings.UPLOAD_DIR)), name="media")
app.mount("/", StaticFiles(directory=str(settings.FRONTEND_DIR), html=True), name="frontend")

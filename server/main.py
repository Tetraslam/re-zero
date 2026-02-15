from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import scans, gateways

app = FastAPI(title="Re:Zero Server", version="0.1.0")

_origins = [settings.frontend_url]
if settings.frontend_url != "http://localhost:3000":
    _origins.append("http://localhost:3000")  # keep local dev working

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scans.router)
app.include_router(gateways.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

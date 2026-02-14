from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import scans, gateways

app = FastAPI(title="Re:Zero Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scans.router)
app.include_router(gateways.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

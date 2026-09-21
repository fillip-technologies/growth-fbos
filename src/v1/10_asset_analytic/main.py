from fastapi import FastAPI
from router import router

app = FastAPI(title="Asset, Analytics & Platform Service", version="1.0.0")
app.include_router(router)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "asset_analytic"}

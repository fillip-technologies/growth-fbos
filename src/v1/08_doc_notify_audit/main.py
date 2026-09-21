from fastapi import FastAPI
from router import router

app = FastAPI(title="Document, Notification & Audit Service", version="1.0.0")
app.include_router(router)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "doc_notify_audit"}

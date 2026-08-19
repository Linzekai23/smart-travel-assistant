from fastapi import FastAPI

from app.api.sse import router as sse_router

app = FastAPI(title="Travel Agent Backend", version="0.1.0")

app.include_router(sse_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}

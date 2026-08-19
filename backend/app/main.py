from fastapi import FastAPI

app = FastAPI(title="Travel Agent Backend", version="0.1.0")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}

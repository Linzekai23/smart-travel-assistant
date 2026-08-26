import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.api.amap_route import router as amap_route_router
from app.api.attraction_image import router as attraction_image_router
from app.api.amap_poi import router as amap_poi_router
from app.api.chat import router as chat_router
from app.api.guide import router as guide_router
from app.api.sse import router as sse_router
from app.api.trips import router as trips_router
from app.llm.deepseek import get_provider

logger = logging.getLogger("travel-agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    try:
        provider = get_provider()
    except RuntimeError as exc:
        # 未配置 DEEPSEEK_API_KEY：应用照常启动，聊天接口返回 503 提示
        app.state.provider = None
        app.state.llm_configured = False
        logger.warning("聊天功能不可用：%s", exc)
    else:
        app.state.provider = provider
        app.state.llm_configured = True
        logger.info("DeepSeek Provider 已配置，图可运行")
    yield


app = FastAPI(title="Travel Agent Backend", version="0.1.0", lifespan=lifespan)
app.state.provider = None
app.state.llm_configured = False

app.include_router(sse_router)
app.include_router(chat_router)
app.include_router(attraction_image_router)
app.include_router(amap_poi_router)
app.include_router(amap_route_router)
app.include_router(guide_router)
app.include_router(trips_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}

"""行程快照 API（"我的行程"列表）。

- 保存：助手行程一键存为快照（POST /api/trips，body = {title, trip_json}）
- 列表/详情/删除：不改变聊天会话模型（sessions/messages/checkpoints 不动）
- user_id 当前恒为 'default'（db 层统一作用域），为多用户预留
"""
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db

router = APIRouter(prefix="/api/trips", tags=["trips"])


class TripCreate(BaseModel):
    title: str = "我的行程"
    trip_json: dict


@router.get("")
def list_trips() -> dict:
    return {"trips": db.list_trips()}


@router.get("/{trip_id}")
def get_trip(trip_id: str) -> dict:
    trip = db.get_trip(trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    return trip


@router.post("")
def create_trip(body: TripCreate) -> dict:
    trip_id = uuid.uuid4().hex
    title = (body.title or "").strip() or "我的行程"
    db.create_trip(trip_id, title, body.trip_json)
    return {"id": trip_id, "title": title}


@router.delete("/{trip_id}")
def delete_trip(trip_id: str) -> dict:
    if not db.delete_trip(trip_id):
        raise HTTPException(status_code=404, detail="行程不存在")
    return {"ok": True}

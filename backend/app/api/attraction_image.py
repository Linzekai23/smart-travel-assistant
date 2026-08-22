"""景点图片 API：按景点名从必应图片搜索（cn.bing.com）取第一张真实图片 URL。

网络实测 Wikipedia/Openverse 被墙、picsum 只有随机图，cn.bing.com 是国内可达且
能返回真实景点照片的图源。抓取结果缓存到 data/attraction_images.json（同一景点
只抓一次，避免反复请求触发反爬）。抓取函数可注入 http_get，测试全 mock 无网络。
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from pathlib import Path

import requests
from fastapi import APIRouter

BING_URL = "https://cn.bing.com/images/search"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# 匹配结果项里的 mediaurl=<URL-encoded 原图>（首条即第一张结果）
MEDIAURL_RE = re.compile(r'mediaurl=((?:%[0-9A-Fa-f]{2}|[^&"<])+)')
# 清洗 LLM 示例标记（如"南桥（示例）"）：直接拿原名搜索会返回无关图（博客配图等）
EXAMPLE_MARK_RE = re.compile(r"[（(]示例[^（()）]*[）)]")


def default_cache_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "attraction_images.json"


class AttractionImageService:
    """图片 URL 解析 + 缓存（json 文件持久化，name → url/时间戳）。"""

    def __init__(self, cache_path: Path | None = None,
                 http_get=None, cache_ttl_days: int = 90) -> None:
        self.cache_path = cache_path or default_cache_path()
        self.http_get = http_get or requests.get
        self.cache_ttl_days = cache_ttl_days
        self._cache: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def _search_bing(self, name: str, city: str | None = None) -> str | None:
        """抓必应图片搜索，返回第一张图片 URL（失败返回 None）。

        搜索词先清洗 LLM 的（示例）标记（如"南桥（示例）"→"南桥"），
        再拼城市消除歧义（"南桥"会命中主板芯片，必须搜"都江堰 南桥"）。
        """
        cleaned = EXAMPLE_MARK_RE.sub("", name).strip() or name
        q = urllib.parse.quote(f"{city} {cleaned}" if city else cleaned)
        try:
            resp = self.http_get(f"{BING_URL}?q={q}&form=HDRSC2",
                                 headers={"User-Agent": UA}, timeout=8)
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        m = MEDIAURL_RE.search(resp.text)
        if not m:
            return None
        # mediaurl 是 URL-encoded 原图（如 https%3a%2f%2f...）；&amp; 需先还原
        return urllib.parse.unquote(m.group(1).replace("&amp;", "&"))

    def get_image_url(self, name: str, city: str | None = None) -> str | None:
        """返回景点图片 URL：命中缓存直接返回；未命中抓必应并缓存。

        缓存 key 带城市（同名景点跨城市不同图，如 南桥/西湖）；无 city 时回退
        纯 name（兼容历史数据与无坐标补全条目）。
        """
        key = f"{city}:{name}" if city else name
        cached = self._cache.get(key)
        if cached and cached.get("url"):
            return cached["url"]
        url = self._search_bing(name, city)
        if url:
            self._cache[key] = {"url": url, "ts": time.strftime("%Y-%m-%d")}
            self._save()
        return url


router = APIRouter()


@router.get("/api/attraction-image")
def attraction_image(name: str, city: str | None = None) -> dict:
    """返回景点真实图片 URL（搜索词带城市消除歧义）；失败返回 {"url": null}。"""
    return {"url": service.get_image_url(name, city)}


service = AttractionImageService()

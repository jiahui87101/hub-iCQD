"""Bocha web-search 的薄封装。

普通 async 函数（不是 SDK tool），返回 SearchResult 字典列表。
返回字段：title / url / snippet / site_name / date。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import BOCHA_API_KEY, BOCHA_BASE_URL
from .models import SearchResult

logger = logging.getLogger(__name__)


def _parse_one(raw: dict[str, Any]) -> SearchResult:
    """把 Bocha 返回的一条结果映射成 SearchResult。字段缺失时尽量兜底。"""
    return SearchResult(
        title=(raw.get("title") or "").strip(),
        url=(raw.get("url") or "").strip(),
        snippet=(raw.get("snippet") or raw.get("summary") or "").strip(),
        site_name=(raw.get("siteName") or raw.get("site_name") or "").strip(),
        date=(raw.get("date") or "").strip(),
    )


async def web_search(query: str, count: int = 10, summary: bool = True) -> list[SearchResult]:
    """调一次 Bocha web-search。

    返回已解析的 SearchResult 列表（按原顺序，重复 URL 已去重）。
    Bocha 文档：POST {BOCHA_BASE_URL}，Authorization: Bearer <key>
    """
    if not BOCHA_API_KEY:
        raise RuntimeError("BOCHA_API_KEY 未配置")

    headers = {
        "Authorization": f"Bearer {BOCHA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"query": query, "count": count, "summary": summary}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(BOCHA_BASE_URL, headers=headers, json=payload)
        resp.raise_for_status()
        body = resp.json()

    # Bocha 实际字段是 data.webPages.value（也有可能在 data.value / data.items）。
    # 按常见形态依次尝试：
    data = body.get("data") or {}
    items: list[dict[str, Any]] = []
    for path in (("webPages", "value"), ("value",), ("items",)):
        cur: Any = data
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                cur = None
                break
        if isinstance(cur, list):
            items = cur
            break

    if not items and isinstance(body.get("results"), list):
        items = body["results"]

    results: list[SearchResult] = []
    seen: set[str] = set()
    for raw in items:
        try:
            r = _parse_one(raw)
        except Exception as exc:  # pragma: no cover
            logger.warning("skip bad result: %s", exc)
            continue
        if not r.url or r.url in seen:
            continue
        seen.add(r.url)
        results.append(r)

    logger.info("web_search query=%r count=%d → %d unique results", query, count, len(results))
    return results


if __name__ == "__main__":
    # 单次搜索 demo（需 .env 已配 BOCHA_API_KEY）
    import asyncio
    import json

    logging.basicConfig(level=logging.INFO)

    async def _demo() -> None:
        rs = await web_search("天空为什么是蓝色的？", count=5)
        out = [
            {"title": r.title, "url": r.url, "site_name": r.site_name, "date": r.date}
            for r in rs
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2))

    asyncio.run(_demo())
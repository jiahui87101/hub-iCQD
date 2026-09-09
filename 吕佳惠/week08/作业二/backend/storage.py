"""本地 JSON 落盘：backend/data/research/{id}.json。

每个写操作都用 threading.Lock 串行化，避免后台 asyncio 写轮询读之间竞态。
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR
from .models import ResearchRecord, ResearchStatus

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_DATA_DIR: Path = DATA_DIR


def ensure_dir() -> Path:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR


def _path(record_id: str) -> Path:
    if not record_id or "/" in record_id or "\\" in record_id:
        raise ValueError(f"非法的 record_id：{record_id!r}")
    return _DATA_DIR / f"{record_id}.json"


def new_id() -> str:
    """生成一个短 id（时间戳 + 8 位 hex）。"""
    return uuid.uuid4().hex[:12]


def create(topic: str) -> ResearchRecord:
    """新建一个 pending 记录并立刻落盘。"""
    rid = new_id()
    rec = ResearchRecord(id=rid, topic=topic, status=ResearchStatus.PENDING)
    save(rec)
    return rec


def load(record_id: str) -> ResearchRecord | None:
    p = _path(record_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return ResearchRecord.model_validate(data)
    except Exception as exc:
        logger.warning("load %s failed: %s", record_id, exc)
        return None


def save(rec: ResearchRecord) -> None:
    """把记录写盘（带锁）。"""
    ensure_dir()
    rec.updated_at = datetime.now()
    p = _path(rec.id)
    tmp = p.with_suffix(".json.tmp")
    payload = rec.model_dump(mode="json")
    with _LOCK:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)


def update(record_id: str, **fields) -> ResearchRecord | None:
    """读 → 改字段 → 写回。"""
    rec = load(record_id)
    if rec is None:
        return None
    for k, v in fields.items():
        setattr(rec, k, v)
    save(rec)
    return rec


def list_all(limit: int = 50) -> list[ResearchRecord]:
    ensure_dir()
    out: list[ResearchRecord] = []
    for p in sorted(_DATA_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(ResearchRecord.model_validate(data))
        except Exception as exc:
            logger.warning("skip %s: %s", p.name, exc)
        if len(out) >= limit:
            break
    return out


def delete(record_id: str) -> bool:
    p = _path(record_id)
    if not p.exists():
        return False
    with _LOCK:
        p.unlink()
    return True


if __name__ == "__main__":
    # 自检：建/读/列/删（自清理，不污染真实数据）
    ensure_dir()
    rid = "smoke-" + new_id()
    rec = ResearchRecord(id=rid, topic="self-test", status=ResearchStatus.RUNNING)
    save(rec)
    loaded = load(rid)
    assert loaded is not None and loaded.topic == "self-test", "round-trip failed"
    update(rid, status=ResearchStatus.COMPLETED)
    again = load(rid)
    assert again is not None and again.status == ResearchStatus.COMPLETED
    listed = list_all()
    assert any(r.id == rid for r in listed)
    delete(rid)
    assert load(rid) is None
    print(f"[storage] smoke ok: created/loaded/updated/listed/deleted {rid}")
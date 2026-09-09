"""统一从项目根 .env 读配置。所有模块都从这里拿 key / 上限。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根 = backend/ 的父目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name, default)
    if required and (val is None or val == ""):
        raise RuntimeError(f"缺少环境变量 {name}，请在 .env 里配置")
    return val or ""


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"环境变量 {name} 不是整数：{raw}") from exc


# DeepSeek（base model）
DEEPSEEK_API_KEY: str = _get("DEEPSEEK_API_KEY", required=True)
DEEPSEEK_BASE_URL: str = _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL: str = _get("DEEPSEEK_MODEL", "deepseek-v4-flash")

# Bocha（web search）
BOCHA_API_KEY: str = _get("BOCHA_API_KEY", required=True)
BOCHA_BASE_URL: str = _get("BOCHA_BASE_URL", "https://api.bocha.cn/v1/web-search")

# 研究引擎
RESEARCH_MAX_ROUNDS: int = _get_int("RESEARCH_MAX_ROUNDS", 3)
LLM_RETRIES: int = _get_int("LLM_RETRIES", 3)

# 服务端口
APP_PORT: int = _get_int("APP_PORT", 8000)

# 数据目录（相对项目根）
DATA_DIR: Path = PROJECT_ROOT / _get("DATA_DIR", "backend/data/research")


def describe() -> dict:
    """自检输出：用于 `python3 -m backend.config` 演示。"""
    return {
        "project_root": str(PROJECT_ROOT),
        "deepseek_model": DEEPSEEK_MODEL,
        "deepseek_base_url": DEEPSEEK_BASE_URL,
        "bocha_base_url": BOCHA_BASE_URL,
        "max_rounds": RESEARCH_MAX_ROUNDS,
        "llm_retries": LLM_RETRIES,
        "app_port": APP_PORT,
        "data_dir": str(DATA_DIR),
        "has_deepseek_key": bool(DEEPSEEK_API_KEY and not DEEPSEEK_API_KEY.startswith("sk-你的")),
        "has_bocha_key": bool(BOCHA_API_KEY and not BOCHA_API_KEY.startswith("sk-your")),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(describe(), ensure_ascii=False, indent=2))
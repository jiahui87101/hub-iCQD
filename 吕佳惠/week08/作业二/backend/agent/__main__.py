"""包级 demo：验证 __init__ 导出 + BaseAgent 模板渲染 + parse_json 兜底。

纯本地逻辑，不需要 .env / 网络。运行方式：
    python3 -m backend.agent
"""
from __future__ import annotations

import json
import logging

from ..models import KeywordOutput
from . import BaseAgent, JudgeAgent, KeywordAgent, ReportAgent, SummaryAgent

logger = logging.getLogger(__name__)


def _check_exports() -> None:
    expected = {"BaseAgent", "KeywordAgent", "SummaryAgent", "JudgeAgent", "ReportAgent"}
    have = {BaseAgent.__name__, KeywordAgent.__name__, SummaryAgent.__name__,
            JudgeAgent.__name__, ReportAgent.__name__}
    missing = expected - have
    assert not missing, f"__init__ 没导出：{missing}"
    print(f"[agent] exports ok: {sorted(expected)}")


def _check_base_render() -> None:
    a = BaseAgent(name="t")
    sys_p, user = a._render(topic="测试主题")  # noqa: SLF001
    assert sys_p and "测试主题" in user, "模板渲染缺字段"
    print(f"[agent] BaseAgent render ok, head={user.splitlines()[0][:30]}")


def _check_parse_json() -> None:
    from .base import parse_json

    raw = "```json\n{\"keywords\": [\"a\", \"b\"]}\n```"
    out = parse_json(raw, KeywordOutput)
    assert out.keywords == ["a", "b"]
    print(f"[agent] parse_json codeblock ok: {out.keywords}")

    raw2 = json.dumps({"keywords": ["x"]}, ensure_ascii=False)
    out2 = parse_json(raw2, KeywordOutput)
    assert out2.keywords == ["x"]
    print(f"[agent] parse_json direct ok: {out2.keywords}")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    _check_exports()
    _check_base_render()
    _check_parse_json()
    print("[agent] all self-checks passed")


if __name__ == "__main__":
    main()
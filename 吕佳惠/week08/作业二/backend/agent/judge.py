"""JudgeAgent：判断当前研究草稿是否足够，不够则给出补检关键词。"""
from __future__ import annotations

import logging

from ..models import DraftBlock, JudgeDecision, SourceItem
from .base import BaseAgent

logger = logging.getLogger(__name__)


class JudgeAgent(BaseAgent):
    template_name = "judge_agent.jinja2"

    async def judge(
        self,
        topic: str,
        draft: list[DraftBlock],
        sources: list[SourceItem],
        searched: list[str],
    ) -> JudgeDecision:
        out = await self.call_json(
            system_vars={},
            user_input_vars={
                "topic": topic,
                "draft": draft,
                "sources": sources,
                "searched": searched,
            },
            output_cls=JudgeDecision,
        )
        # 兜底：空字符串 reason 不算 None
        out.new_keywords = [k.strip() for k in out.new_keywords if k and k.strip()]
        logger.info(
            "JudgeAgent: sufficient=%s new=%d reason=%s",
            out.sufficient, len(out.new_keywords), out.reason,
        )
        return out


if __name__ == "__main__":
    import asyncio

    from ..models import DraftBlock, SourceItem

    logging.basicConfig(level=logging.INFO)

    async def _demo() -> None:
        agent = JudgeAgent()
        out = await agent.judge(
            topic="测试主题",
            draft=[DraftBlock(keyword="A", text="示例草稿段落...")],
            sources=[SourceItem(url="https://x", title="t", citation_label="[1]")],
            searched=["A"],
        )
        print(out.model_dump_json(ensure_ascii=False, indent=2))

    asyncio.run(_demo())
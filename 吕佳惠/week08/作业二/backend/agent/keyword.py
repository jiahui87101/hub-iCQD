"""KeywordAgent：把研究主题拆成 3~6 个并行搜索关键词。"""
from __future__ import annotations

import logging

from ..models import KeywordOutput
from .base import BaseAgent

logger = logging.getLogger(__name__)


class KeywordAgent(BaseAgent):
    template_name = "keyword_agent.jinja2"

    async def generate_keywords(self, topic: str) -> list[str]:
        out = await self.call_json(
            system_vars={},
            user_input_vars={"topic": topic},
            output_cls=KeywordOutput,
        )
        keywords = [k.strip() for k in out.keywords if k and k.strip()]
        logger.info("KeywordAgent: topic=%r → %d keywords: %s", topic, len(keywords), keywords)
        return keywords


if __name__ == "__main__":
    # 真实调用需要 .env 里有 DeepSeek key + 网络
    import asyncio

    logging.basicConfig(level=logging.INFO)

    async def _demo() -> None:
        agent = KeywordAgent()
        kws = await agent.generate_keywords("2026 年大模型 API 价格走势")
        for k in kws:
            print("-", k)

    asyncio.run(_demo())
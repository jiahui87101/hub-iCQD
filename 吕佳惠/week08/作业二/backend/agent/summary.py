"""SummaryAgent：把一条关键词对应的搜索结果总结成一段正文文字。

注意：本 agent 输出纯文本（不是 JSON），所以走 call_text 不用 parse_json。
"""
from __future__ import annotations

import logging

from ..models import SearchResult
from .base import BaseAgent

logger = logging.getLogger(__name__)


class SummaryAgent(BaseAgent):
    template_name = "summary_agent.jinja2"

    async def summarize(self, topic: str, keyword: str, results: list[SearchResult]) -> str:
        text = await self.call_text(
            system_vars={},
            user_input_vars={"topic": topic, "keyword": keyword, "results": results},
        )
        # 简单规范化：去收尾空白、多余空行压一行
        text = text.strip()
        text = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
        logger.info(
            "SummaryAgent: topic=%r keyword=%r results=%d → %d chars",
            topic, keyword, len(results), len(text),
        )
        return text


if __name__ == "__main__":
    # 真实调用需要 .env 里有 DeepSeek key + 网络（构造几条假搜索结果也能跑）
    import asyncio

    from ..models import SearchResult

    logging.basicConfig(level=logging.INFO)

    async def _demo() -> None:
        agent = SummaryAgent()
        rs = [
            SearchResult(
                title="示例标题 1",
                url="https://example.com/1",
                snippet="示例摘要内容...",
                site_name="example.com",
                date="2026-01-01",
            )
        ]
        text = await agent.summarize("测试主题", "示例关键词", rs)
        print(text)

    asyncio.run(_demo())
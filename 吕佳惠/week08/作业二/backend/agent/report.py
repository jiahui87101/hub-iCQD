"""ReportAgent：基于草稿+来源产出结构化报告（ReportOutline）+ 自包含 HTML。

按 CLAUDE.md：generate 调两次 LLM——先元信息（title/summary/key_conclusions/open_questions），
再把组装好的 ReportContent 渲染成 HTML。
"""
from __future__ import annotations

import logging

from ..models import (
    Confidence,
    DraftBlock,
    ReportContent,
    ReportOutline,
    ReportSection,
    SourceItem,
)
from .base import BaseAgent

logger = logging.getLogger(__name__)


class ReportAgent(BaseAgent):

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name=name)
        # 两个角色共用一个 BaseAgent，但模板名不同——实例属性覆盖
        self._outline_template = "report_agent.jinja2"
        self._html_template = "report_html_agent.jinja2"

    # ---------- 元信息：一次 LLM ----------

    async def _render_outline(self, **vars) -> tuple[str, str]:
        # 借 BaseAgent._render 但换模板名
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        from pathlib import Path as _P

        env = Environment(
            loader=FileSystemLoader(str(_P(__file__).resolve().parent.parent / "templates")),
            autoescape=select_autoescape(enabled_extensions=("jinja2",)),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        user_input = env.get_template(self._outline_template).render(**vars)
        return ("你是严谨的研究分析师，严格按用户提示词格式输出 JSON。", user_input)

    async def _render_html(self, **vars) -> tuple[str, str]:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        from pathlib import Path as _P

        env = Environment(
            loader=FileSystemLoader(str(_P(__file__).resolve().parent.parent / "templates")),
            autoescape=select_autoescape(enabled_extensions=("jinja2",)),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        user_input = env.get_template(self._html_template).render(**vars)
        return ("你是排版工程师，直接输出 HTML，不要任何解释。", user_input)

    async def _outline(
        self,
        topic: str,
        draft: list[DraftBlock],
        sources: list[SourceItem],
        confidence_hint: str,
    ) -> ReportOutline:
        sys_p, user_input = await self._render_outline(
            topic=topic, draft=draft, sources=sources, confidence_hint=confidence_hint
        )
        from .base import parse_json

        text = await self._run(user_input, sys_p)
        outline = parse_json(text, ReportOutline)
        logger.info(
            "ReportAgent: outline title=%r conclusions=%d open=%d",
            outline.title, len(outline.key_conclusions), len(outline.open_questions),
        )
        return outline

    # ---------- HTML：一次 LLM ----------

    async def _html(
        self,
        report: ReportContent,
        sources: list[SourceItem],
        confidence: Confidence,
    ) -> str:
        sys_p, user_input = await self._render_html(
            title=report.title,
            summary=report.summary,
            sections=report.sections,
            key_conclusions=report.key_conclusions,
            open_questions=report.open_questions,
            sources=sources,
            confidence_level=confidence.level,
            cutoff_note=confidence.cutoff_note,
        )
        html = await self._run(user_input, sys_p)
        # 兜底去掉 ```html``` 包裹
        if html.startswith("```"):
            html = html.strip("`").strip()
            first_nl = html.find("\n")
            if 0 < first_nl <= 12:
                head = html[:first_nl].strip()
                if head and " " not in head and "{" not in head and "<" not in head:
                    html = html[first_nl + 1 :].strip()
        # 兜底：必须以 <!DOCTYPE 或 <html 开头
        if not (html.lstrip().lower().startswith("<!doctype") or html.lstrip().lower().startswith("<html")):
            logger.warning("ReportAgent: HTML output didn't start with doctype/html, wrapping raw")
            html = (
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>"
                + report.title
                + "</title></head><body><pre>"
                + html.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                + "</pre></body></html>"
            )
        return html

    # ---------- 对外主入口 ----------

    async def generate(
        self,
        topic: str,
        draft: list[DraftBlock],
        sources: list[SourceItem],
        confidence: Confidence,
    ) -> tuple[ReportContent, str]:
        """两次 LLM：先 outline，再 HTML。

        sections 不走 LLM，按 draft 段落直接映射（heading=keyword、body=text），
        由 outline 的 title/summary/key_conclusions/open_questions 组装 ReportContent。
        """
        confidence_hint = (
            f"信息来源覆盖度：{confidence.coverage or '未知'}；"
            f"信息截止：{confidence.cutoff_note or '未知'}；"
            f"模型推断项数：{len(confidence.inferred_conclusions)}"
        )
        outline = await self._outline(topic, draft, sources, confidence_hint)

        sections = [
            ReportSection(heading=blk.keyword, body=blk.text)
            for blk in draft
            if blk.text and blk.text.strip()
        ]
        report = ReportContent(
            title=outline.title,
            summary=outline.summary,
            sections=sections,
            key_conclusions=outline.key_conclusions,
            open_questions=outline.open_questions,
        )

        html = await self._html(report, sources, confidence)
        return report, html


if __name__ == "__main__":
    # 真实调用需要 .env 里有 DeepSeek key + 网络
    import asyncio

    from ..models import Confidence, DraftBlock, SourceItem

    logging.basicConfig(level=logging.INFO)

    async def _demo() -> None:
        agent = ReportAgent()
        draft = [DraftBlock(keyword="示例维度", text="这是该维度的总结文字……")]
        sources = [SourceItem(url="https://x", title="示例", citation_label="[1]")]
        conf = Confidence(level="medium", coverage="覆盖度一般", cutoff_note="2026-01")
        report, html = await agent.generate("测试主题", draft, sources, conf)
        print("title:", report.title)
        print("summary:", report.summary)
        print("key_conclusions:", report.key_conclusions)
        print("open_questions:", report.open_questions)
        print("html_len:", len(html))

    asyncio.run(_demo())
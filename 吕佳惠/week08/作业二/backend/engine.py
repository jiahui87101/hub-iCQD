"""DeepResearch：研究引擎（编排器，不参与 LLM 调用）。

按 CLAUDE.md 描述：
  规划（KeywordAgent）
    → 逐关键词 web_search（直接函数调用）
    → SummaryAgent 把搜索结果总结成一段正文并**直接累积进草稿 draft**
    → JudgeAgent 判断草稿是否够，不够则用新关键词进下一轮（最多 max_rounds 轮）
    → 收集来源 + 确定性计算置信度
    → ReportAgent 产出结构化报告 + HTML

每完成一轮（含规划）通过 ``on_progress(snapshot)`` 回调把中间结果传出去——
research.py 的 on_progress 会落盘。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Union

from .agent import JudgeAgent, KeywordAgent, ReportAgent, SummaryAgent
from .config import RESEARCH_MAX_ROUNDS
from .models import (
    Confidence,
    DraftBlock,
    ProcessStep,
    ReportContent,
    ResearchProcess,
    ResearchRecord,
    ResearchStatus,
    SearchResult,
    SourceItem,
)
from .tools import web_search

logger = logging.getLogger(__name__)


ProgressCallback = Union[
    Callable[[dict[str, Any]], None],
    Callable[[dict[str, Any]], Awaitable[None]],
]


# ============================================================
# 确定性工具
# ============================================================


def _merge_sources(existing: list[SourceItem], new: list[SearchResult]) -> tuple[list[SourceItem], list[SearchResult]]:
    """把新搜索结果并入 SourceItem 列表（按 URL 去重保序），返回更新后的列表与新增的 SourceItem。"""
    seen = {s.url for s in existing}
    added: list[SourceItem] = []
    for idx, r in enumerate(new, start=1):
        if not r.url or r.url in seen:
            continue
        seen.add(r.url)
        # citation_label 用 [1]/[2]/... 顺序编号
        label = f"[{len(existing) + len(added) + 1}]"
        added.append(
            SourceItem(
                url=r.url,
                title=r.title,
                site_name=r.site_name,
                snippet=r.snippet,
                date=r.date,
                citation_label=label,
            )
        )
    return existing + added, added


def _compute_confidence(draft: list[DraftBlock], sources: list[SourceItem], rounds: int) -> Confidence:
    """基于已检索关键词数 + 来源覆盖 + 轮数做确定性置信度评估。

    启发式：
    - 轮数越多、来源越少 → low
    - 来源 ≥ 6 + 至少 3 个不同关键词 → high
    - 其他 → medium
    """
    coverage = f"已覆盖 {len(draft)} 个子维度，{len(sources)} 条来源"
    cutoff = datetime.now().strftime("%Y-%m")  # 信息截止时间粗略到月份
    if len(sources) >= 6 and len(draft) >= 3:
        level = "high"
    elif len(sources) <= 2 or rounds >= RESEARCH_MAX_ROUNDS:
        level = "low"
    else:
        level = "medium"
    return Confidence(
        level=level,
        coverage=coverage,
        cutoff_note=f"{cutoff}（基于搜索引擎结果时间戳）",
        inferred_conclusions=[],  # 严格落地由 report 阶段填
    )


# ============================================================
# 引擎
# ============================================================


class DeepResearch:
    """研究引擎。run() 是异步主入口；on_progress 在每轮完成后回调一次。"""

    def __init__(
        self,
        topic: str,
        *,
        max_rounds: int = RESEARCH_MAX_ROUNDS,
    ) -> None:
        self.topic = topic
        self.max_rounds = max_rounds

        self.keyword_agent = KeywordAgent()
        self.summary_agent = SummaryAgent()
        self.judge_agent = JudgeAgent()
        self.report_agent = ReportAgent()

        # 中间结果
        self.draft: list[DraftBlock] = []
        self.sources: list[SourceItem] = []
        self.process = ResearchProcess()

        # 最终产物
        self.report: ReportContent | None = None
        self.report_html: str | None = None
        self.confidence: Confidence | None = None

    # ---------- 进度回调（支持 sync / async） ----------

    async def _progress(self, on_progress: ProgressCallback | None) -> None:
        if on_progress is None:
            return
        snapshot = {
            "topic": self.topic,
            "status": ResearchStatus.RUNNING.value,
            "process": self.process.model_dump(),
            "draft": [b.model_dump() for b in self.draft],
            "sources": [s.model_dump() for s in self.sources],
        }
        if inspect.isawaitable(on_progress):
            await on_progress(snapshot)  # type: ignore[arg-type]
        else:
            on_progress(snapshot)

    # ---------- 单关键词一轮 ----------

    async def _process_keyword(self, keyword: str) -> list[SearchResult]:
        """对单个关键词跑一次 web_search，返回 SearchResult 列表。"""
        try:
            results = await web_search(keyword, count=10, summary=True)
        except Exception as exc:
            logger.warning("web_search 失败 keyword=%r: %s", keyword, exc)
            results = []
        # 记录搜索关键词与已读 URL
        if keyword not in self.process.search_queries:
            self.process.search_queries.append(keyword)
        for r in results:
            if r.url and r.url not in self.process.reviewed_urls:
                self.process.reviewed_urls.append(r.url)
        self.process.steps.append(
            ProcessStep(step="search", detail=f"检索 [{keyword}] 返回 {len(results)} 条结果")
        )
        return results

    async def _summarize_keyword(self, keyword: str, results: list[SearchResult]) -> str:
        if not results:
            text = "（本次搜索未返回可用结果，相关维度信息缺失。）"
        else:
            try:
                text = await self.summary_agent.summarize(self.topic, keyword, results)
            except Exception as exc:
                logger.warning("SummaryAgent 失败 keyword=%r: %s", keyword, exc)
                text = "（该维度总结失败，跳过。）"
        self.draft.append(DraftBlock(keyword=keyword, text=text))
        self.process.steps.append(
            ProcessStep(step="summarize", detail=f"已总结 [{keyword}]，正文 {len(text)} 字")
        )
        return text

    async def _run_keyword_round(self, keyword: str) -> None:
        results = await self._process_keyword(keyword)
        await self._summarize_keyword(keyword, results)
        # 合并来源（不重复）
        self.sources, _ = _merge_sources(self.sources, results)

    # ---------- 主入口 ----------

    async def run(self, on_progress: ProgressCallback | None = None) -> ResearchRecord:
        """完整跑一次研究；异常会记录到 record.error 上抛。"""
        logger.info("DeepResearch start topic=%r max_rounds=%d", self.topic, self.max_rounds)

        # 1) 规划
        try:
            plan_keywords = await self.keyword_agent.generate_keywords(self.topic)
        except Exception as exc:
            plan_keywords = [self.topic]  # 兜底：直接用主题作为关键词
            logger.warning("KeywordAgent 失败，用主题兜底：%s", exc)
        if not plan_keywords:
            plan_keywords = [self.topic]
        self.process.plan = plan_keywords
        self.process.iterations = 0
        self.process.steps.append(
            ProcessStep(step="plan", detail=f"规划 {len(plan_keywords)} 个关键词：{plan_keywords}")
        )
        await self._progress(on_progress)

        # 2) 多轮：每轮跑一批关键词 → judge 决定是否继续
        pending: list[str] = list(plan_keywords)
        for round_idx in range(1, self.max_rounds + 1):
            self.process.iterations = round_idx
            logger.info("DeepResearch round %d/%d, pending=%d", round_idx, self.max_rounds, len(pending))

            # 2a) 跑完本轮所有待办关键词
            for kw in pending:
                await self._run_keyword_round(kw)

            # 2b) judge：本轮草稿是否够用
            try:
                decision = await self.judge_agent.judge(
                    topic=self.topic,
                    draft=self.draft,
                    sources=self.sources,
                    searched=self.process.search_queries,
                )
            except Exception as exc:
                logger.warning("JudgeAgent 失败，按充分处理：%s", exc)
                decision = None  # type: ignore[assignment]

            if decision is not None:
                self.process.steps.append(
                    ProcessStep(
                        step="judge",
                        detail=(
                            f"判断 sufficient={decision.sufficient}；"
                            f"新增 {len(decision.new_keywords)} 个关键词；{decision.reason}"
                        ),
                    )
                )

            await self._progress(on_progress)

            # 2c) 收敛条件
            if decision is None or decision.sufficient:
                break
            new_kws = [k for k in decision.new_keywords if k and k.strip()]
            if not new_kws:
                break
            pending = new_kws

        # 3) 计算置信度
        self.confidence = _compute_confidence(self.draft, self.sources, self.process.iterations)

        # 4) 报告
        if not self.draft:
            # 极端兜底：让报告不空白
            self.draft = [DraftBlock(keyword="概览", text="本次研究未能检索到任何有效结果，无法生成正文。")]

        try:
            self.report, self.report_html = await self.report_agent.generate(
                topic=self.topic,
                draft=self.draft,
                sources=self.sources,
                confidence=self.confidence,
            )
        except Exception as exc:
            logger.exception("ReportAgent 失败")
            # 兜底：用最小可用报告
            self.report = ReportContent(
                title=self.topic,
                summary="（报告生成失败，仅保留研究草稿）",
                sections=[
                    {"heading": b.keyword, "body": b.text} for b in self.draft
                ],  # type: ignore[arg-type]
                key_conclusions=[],
                open_questions=["报告生成阶段异常，请查看 error 字段"],
            )
            self.report_html = (
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>"
                + self.topic
                + "</title></head><body><h1>"
                + self.topic
                + "</h1><p>报告生成失败，仅保留研究草稿。</p></body></html>"
            )
            raise

        self.process.steps.append(
            ProcessStep(step="report", detail=f"已生成报告：{self.report.title}")
        )

        # 收尾：构造 record
        rec = ResearchRecord(
            id="",  # 由 research.py 在落盘前填
            topic=self.topic,
            status=ResearchStatus.COMPLETED,
            draft=self.draft,
            sources=self.sources,
            process=self.process,
            report=self.report,
            report_html=self.report_html,
            confidence=self.confidence,
        )
        await self._progress(on_progress)
        logger.info("DeepResearch done topic=%r iterations=%d", self.topic, self.process.iterations)
        return rec


if __name__ == "__main__":
    # 端到端 demo（需 .env key + 网络）
    logging.basicConfig(level=logging.INFO)

    async def _demo() -> None:
        eng = DeepResearch("2026 年大模型 API 价格走势", max_rounds=2)

        def _on_prog(snap: dict[str, Any]) -> None:
            print(
                f"  ↳ progress: iter={snap['process']['iterations']} "
                f"queries={len(snap['process']['search_queries'])} "
                f"drafts={len(snap['draft'])} sources={len(snap['sources'])}"
            )

        rec = await eng.run(on_progress=_on_prog)
        print("title:", rec.report.title if rec.report else None)
        print("sections:", len(rec.report.sections) if rec.report else 0)
        print("confidence:", rec.confidence)

    asyncio.run(_demo())
"""所有 pydantic 模型集中定义在 models.py。

包括：
- 四类产物：ReportContent / ReportHTML / Sources / ResearchProcess / Confidence
- 中间结果：KeywordOutput / JudgeDecision / DraftBlock / ReportOutline / ProcessStep
- 落盘结构：ResearchRecord / ResearchStatus
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ============================================================
# 状态机
# ============================================================


class ResearchStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================================
# 中间结果（agent 产出）
# ============================================================


class KeywordOutput(BaseModel):
    """KeywordAgent 输出：拆解主题产生的搜索关键词。"""

    keywords: list[str] = Field(..., description="3~6 个并行检索关键词")


class SearchResult(BaseModel):
    """Bocha 解析后的一条搜索结果。"""

    title: str
    url: str
    snippet: str = ""
    site_name: str = ""
    date: str = ""


class DraftBlock(BaseModel):
    """SummaryAgent 产出的一段正文：keyword → 一段文字。"""

    keyword: str
    text: str


class JudgeDecision(BaseModel):
    """JudgeAgent 输出：当前轮草稿是否够用。"""

    sufficient: bool = Field(..., description="草稿是否已经足够")
    new_keywords: list[str] = Field(default_factory=list, description="若不足，需补充的关键词")
    reason: str = Field(default="", description="判断理由（人类可读）")


class ReportSection(BaseModel):
    """报告的一个分节：标题 + 正文。"""

    heading: str
    body: str


class ReportOutline(BaseModel):
    """ReportAgent 第一阶段输出：报告元信息 JSON。"""

    title: str
    summary: str
    key_conclusions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


# ============================================================
# 四类产物（最终交付）
# ============================================================


class SourceItem(BaseModel):
    """一条来源记录。"""

    url: str
    title: str
    site_name: str = ""
    snippet: str = ""
    citation_label: str = Field(default="", description="正文里引用时的简写，如 [1]")


class ReportContent(BaseModel):
    """结构化研究报告。"""

    title: str
    summary: str
    sections: list[ReportSection] = Field(default_factory=list)
    key_conclusions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


# report_html 用字符串存 HTML 原文（避免 JSON 转义出错）
ReportHTML = str


class ProcessStep(BaseModel):
    """研究过程的一步记录。"""

    step: Literal["plan", "search", "summarize", "judge", "report"]
    detail: str


class ResearchProcess(BaseModel):
    """研究过程记录：检索了哪些关键词、读了哪些页面、迭代了几轮。"""

    plan: list[str] = Field(default_factory=list, description="初始规划关键词")
    search_queries: list[str] = Field(default_factory=list, description="全部检索关键词（去重保序）")
    reviewed_urls: list[str] = Field(default_factory=list, description="已读页面的 URL（去重保序）")
    iterations: int = 0
    steps: list[ProcessStep] = Field(default_factory=list)


class Confidence(BaseModel):
    """置信度说明。"""

    level: Literal["high", "medium", "low"] = "medium"
    coverage: str = Field(default="", description="信息来源覆盖度描述")
    cutoff_note: str = Field(default="", description="信息截止时间")
    inferred_conclusions: list[str] = Field(default_factory=list, description="无来源支撑、仅靠模型推断的结论")


# ============================================================
# 落盘结构
# ============================================================


class ResearchRecord(BaseModel):
    """完整研究记录：状态 + 四类产物 + 过程 + 中间草稿。"""

    id: str
    topic: str
    status: ResearchStatus = ResearchStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    error: str | None = None

    # 中间结果（运行中逐步累积）
    draft: list[DraftBlock] = Field(default_factory=list)
    sources: list[SourceItem] = Field(default_factory=list)
    process: ResearchProcess = Field(default_factory=ResearchProcess)

    # 最终产物
    report: ReportContent | None = None
    report_html: ReportHTML | None = None
    confidence: Confidence | None = None


# ============================================================
# API 进出参
# ============================================================


class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)


class ResearchCreated(BaseModel):
    research_id: str


if __name__ == "__main__":
    # 模型序列化自检（不需要 key）
    import json

    kw = KeywordOutput(keywords=["A", "B"])
    jd = JudgeDecision(sufficient=False, new_keywords=["C"], reason="还需要补检")
    sec = ReportSection(heading="h", body="b")
    src = SourceItem(url="https://x", title="t", citation_label="[1]")
    rec = ResearchRecord(
        id="demo",
        topic="demo",
        draft=[DraftBlock(keyword="A", text="aaa")],
        sources=[src],
        process=ResearchProcess(plan=["A"], search_queries=["A"], iterations=1),
        report=ReportContent(title="t", summary="s", sections=[sec]),
        confidence=Confidence(level="high", coverage="ok", cutoff_note="2026-01"),
    )

    print("KeywordOutput:", kw.model_dump_json(ensure_ascii=False))
    print("JudgeDecision:", jd.model_dump_json(ensure_ascii=False))
    print("ResearchRecord ok, id=", rec.id)
    print("status enum values:", [s.value for s in ResearchStatus])
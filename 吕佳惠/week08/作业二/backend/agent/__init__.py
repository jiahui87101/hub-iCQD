"""角色 agent 包。

每个 .py 是一个独立角色，继承 BaseAgent，提示词从 templates/ 渲染。
本包不含编排——编排逻辑在 backend.engine.DeepResearch。

- KeywordAgent: 主题 → 搜索关键词
- SummaryAgent: 关键词+搜索结果 → 一段正文（不走 JSON）
- JudgeAgent: 草稿+来源 → 是否补检+新关键词
- ReportAgent: 草稿+来源 → 结构化报告 + HTML
"""
from .base import BaseAgent
from .judge import JudgeAgent
from .keyword import KeywordAgent
from .report import ReportAgent
from .summary import SummaryAgent

__all__ = [
    "BaseAgent",
    "KeywordAgent",
    "SummaryAgent",
    "JudgeAgent",
    "ReportAgent",
]
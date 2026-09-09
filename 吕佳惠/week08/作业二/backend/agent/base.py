"""BaseAgent：所有角色 agent 的基类。

职责：
- 用 openai-agents SDK + DeepSeek base model 发起一次 LLM 调用；
- 渲染 Jinja2 提示词模板；
- 处理 DeepSeek 偶发空输出（自动重试 LLM_RETRIES 次）；
- 解析 JSON 输出（pydantic 直接解析 + ```json``` 代码块正则兜底）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, TypeVar

from jinja2 import Environment, FileSystemLoader, select_autoescape
from openai_agents import Agent, Runner, set_default_openai_api, set_tracing_disabled
from pydantic import BaseModel

from ..config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    LLM_RETRIES,
)

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_JINJA = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("jinja2",)),
    trim_blocks=True,
    lstrip_blocks=True,
)

T = TypeVar("T", bound=BaseModel)


# ---- SDK 全局初始化（模块级，进程内只跑一次） ----
# DeepSeek 兼容 OpenAI ChatCompletions API，告知 SDK。
set_default_openai_api("chat_completions")
# 关掉 tracing，避免 SDK 试图上报到 Anthropic 的 trace 端点。
set_tracing_disabled(True)


def _init_sdk_env() -> None:
    """把 DeepSeek 的 key / base_url 注入到 OpenAI SDK 默认环境变量。

    openai-agents SDK 默认会从环境变量读 OPENAI_API_KEY / OPENAI_BASE_URL，
    这样不用在每个 Agent 上重复传参。
    """
    os.environ.setdefault("OPENAI_API_KEY", DEEPSEEK_API_KEY)
    os.environ.setdefault("OPENAI_BASE_URL", DEEPSEEK_BASE_URL)


_init_sdk_env()


# ---- JSON 解析兜底 ----

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
_JSON_FIRST = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def parse_json(text: str, model: type[T]) -> T:
    """把模型输出解析成 pydantic 实例。

    优先用 model_validate_json；失败时尝试从 ```json``` 代码块里抠 JSON；再失败时退到首段大括号。
    """
    text = text.strip()
    # 1. 直接解析
    try:
        return model.model_validate_json(text)
    except Exception:
        pass

    # 2. ```json``` 代码块
    m = _JSON_BLOCK.search(text)
    if m:
        try:
            return model.model_validate_json(m.group(1))
        except Exception:
            pass

    # 3. 抓首段 JSON
    m = _JSON_FIRST.search(text)
    if m:
        try:
            return model.model_validate_json(m.group(1))
        except Exception as exc:
            raise ValueError(f"无法从模型输出解析 {model.__name__}: {exc}\n原始输出：{text[:500]}") from exc

    raise ValueError(f"模型输出里没有 JSON：{text[:500]}")


class BaseAgent:
    """所有角色 agent 的基类。

    子类只需要覆盖 ``template_name``，并在需要 JSON 输出时调用 ``call_json``；
    需要纯文本时调用 ``call_text``（SummaryAgent 用）。
    """

    template_name: str = ""

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.__class__.__name__
        self._agent = Agent(
            name=self.name,
            model=DEEPSEEK_MODEL,
            instructions="你是严谨的研究助手。严格遵守用户提示词里的输出格式要求。",
        )

    # ---------- 模板渲染 ----------

    def _render(self, **vars: Any) -> tuple[str, str]:
        """渲染模板，返回 (system_prompt, user_input)。

        默认 system_prompt 极简，所有约束放在 user_input（模板里）。
        """
        if not self.template_name:
            raise ValueError(f"{self.__class__.__name__} 没指定 template_name")
        tpl = _JINJA.get_template(self.template_name)
        user_input = tpl.render(**vars)
        return ("你是严谨的研究助手，严格按用户提示词格式输出。", user_input)

    # ---------- LLM 调用 ----------

    async def _run(self, user_input: str, system_prompt: str) -> str:
        """发起一次 LLM 调用，自动重试空输出。返回原始 content 字符串。"""
        last_err: Exception | None = None
        for attempt in range(1, LLM_RETRIES + 1):
            t0 = time.time()
            logger.debug(
                "[%s] LLM call attempt %d/%d, user_input_len=%d",
                self.name, attempt, LLM_RETRIES, len(user_input),
            )
            try:
                # openai-agents Runner.run 是 async；SDK 走 chat_completions。
                result = await Runner.run(
                    self._agent,
                    input=user_input,
                    system_prompt=system_prompt,
                )
                content = (result.final_output or "").strip()
            except Exception as exc:
                last_err = exc
                logger.warning("[%s] LLM call failed: %s", self.name, exc)
                await _sleep_backoff(attempt)
                continue

            elapsed = time.time() - t0
            if not content:
                # DeepSeek 偶发 200 + 空 content，按 CLAUDE.md 自动重试
                logger.warning("[%s] empty output, retry %d/%d", self.name, attempt, LLM_RETRIES)
                await _sleep_backoff(attempt)
                continue

            logger.info(
                "[%s] LLM ok in %.1fs, output_len=%d",
                self.name, elapsed, len(content),
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[%s] final_output=%s", self.name, content[:1000])
            return content

        raise RuntimeError(
            f"{self.name} LLM 调用连续 {LLM_RETRIES} 次失败：{last_err}"
        )

    # ---------- 对外主入口 ----------

    async def call_json(
        self,
        system_vars: dict[str, Any],
        user_input_vars: dict[str, Any],
        output_cls: type[T],
    ) -> T:
        """模板渲染 + LLM + parse_json。SummaryAgent 不用这个。"""
        sys_p, user_input = self._render(**system_vars, **user_input_vars)
        text = await self._run(user_input, sys_p)
        return parse_json(text, output_cls)

    async def call_text(
        self,
        system_vars: dict[str, Any],
        user_input_vars: dict[str, Any],
    ) -> str:
        """纯文本调用：模板渲染 + LLM，返回字符串（SummaryAgent 用）。

        SummaryAgent 模板已经要求直接输出正文，但仍兜底去掉可能的 ``` 包裹。
        """
        sys_p, user_input = self._render(**system_vars, **user_input_vars)
        text = await self._run(user_input, sys_p)
        # 兜底：如果模型多手加了代码块，去掉
        if text.startswith("```") and text.endswith("```"):
            text = text.strip("`").strip()
            first_nl = text.find("\n")
            if 0 < first_nl <= 12:
                head = text[:first_nl].strip()
                if head and " " not in head and "{" not in head:
                    text = text[first_nl + 1 :].strip()
        return text


async def _sleep_backoff(attempt: int) -> None:
    """退避 1 秒 * attempt，简单够用。"""
    await asyncio.sleep(1.0 * attempt)


if __name__ == "__main__":
    # parse_json + 模板渲染自检（无需网络/密钥）
    from ..models import KeywordOutput

    agent_dummy = BaseAgent(name="dummy")
    sys_p, user = agent_dummy._render(topic="测试主题")  # noqa: SLF001
    print("rendered user_input head:", user.splitlines()[0])

    bad1 = "下面是 JSON：\n```json\n{\"keywords\": [\"A\", \"B\"]}\n```"
    print("parse_json #1:", parse_json(bad1, KeywordOutput).keywords)

    bad2 = "前缀废话 {\"keywords\": [\"X\"]} 尾巴"
    print("parse_json #2:", parse_json(bad2, KeywordOutput).keywords)

    direct = json.dumps({"keywords": ["k"]}, ensure_ascii=False)
    print("parse_json #3:", parse_json(direct, KeywordOutput).keywords)
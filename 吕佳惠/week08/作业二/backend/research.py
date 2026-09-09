"""研究编排：把一次研究请求拆成"建记录 → 后台跑引擎 → 中间结果落盘 → 终态落盘"。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .engine import DeepResearch
from .models import ResearchRecord, ResearchStatus
from .storage import create, load, update

logger = logging.getLogger(__name__)


class ResearchService:
    """把 DeepResearch 包成"建 id → 后台执行 → 中间结果逐步落盘"。"""

    @staticmethod
    def submit(topic: str) -> ResearchRecord:
        """同步方法：建一条 pending 记录，立刻返回；后台任务在调用方启动。"""
        rec = create(topic)
        logger.info("research submitted: id=%s topic=%r", rec.id, rec.topic)
        return rec

    @staticmethod
    def get(rid: str) -> ResearchRecord | None:
        return load(rid)

    @staticmethod
    def list_recent(limit: int = 50) -> list[ResearchRecord]:
        from .storage import list_all
        return list_all(limit=limit)

    @staticmethod
    async def run_research(rid: str) -> None:
        """后台任务入口：把 record 切到 running → 跑引擎 → 写最终态。

        on_progress 是 async 函数：每次 engine._progress 触发时把中间结果写盘。
        """
        rec = load(rid)
        if rec is None:
            logger.error("run_research: id=%s not found", rid)
            return
        rec.status = ResearchStatus.RUNNING
        update(rid, status=rec.status)

        async def _on_progress(snapshot: dict[str, Any]) -> None:
            # engine 每次推过来都覆盖 process / draft / sources（status 保持 running）
            update(
                rid,
                process=snapshot["process"],
                draft=snapshot["draft"],
                sources=snapshot["sources"],
                status=ResearchStatus.RUNNING,
            )

        try:
            eng = DeepResearch(rec.topic)
            finished = await eng.run(on_progress=_on_progress)
            update(
                rid,
                status=ResearchStatus.COMPLETED,
                draft=finished.draft,
                sources=finished.sources,
                process=finished.process,
                report=finished.report,
                report_html=finished.report_html,
                confidence=finished.confidence,
                error=None,
            )
            logger.info("research completed: id=%s", rid)
        except Exception as exc:
            logger.exception("research failed: id=%s", rid)
            update(rid, status=ResearchStatus.FAILED, error=str(exc))


def launch(rid: str) -> asyncio.Task:
    """给 app.py 用：从 sync 上下文启动后台 asyncio 任务。"""
    return asyncio.create_task(ResearchService.run_research(rid))


if __name__ == "__main__":
    # 端到端 demo：建一条 → 后台跑 → 轮询 → 看到 completed 就打印摘要
    import time

    logging.basicConfig(level=logging.INFO)

    def _run() -> None:
        rec = ResearchService.submit("2026 年大模型 API 价格走势")
        rid = rec.id
        print(f"submitted: {rid}")

        # 用 asyncio.run 跑后台任务
        async def _poll() -> None:
            task = launch(rid)
            while not task.done():
                await asyncio.sleep(0.5)
                r = ResearchService.get(rid)
                if r:
                    print(
                        f"  status={r.status.value} drafts={len(r.draft)} "
                        f"sources={len(r.sources)} iters={r.process.iterations}"
                    )
            await task  # 取异常

        try:
            asyncio.run(_poll())
        except Exception as exc:
            print(f"research failed: {exc}")

        final = ResearchService.get(rid)
        if final and final.report:
            print("title:", final.report.title)
            print("summary:", final.report.summary)
            print("html_len:", len(final.report_html or ""))
            print("confidence:", final.confidence)

        # 清理
        from .storage import delete
        delete(rid)

    t0 = time.time()
    _run()
    print(f"\nelapsed: {time.time() - t0:.1f}s")
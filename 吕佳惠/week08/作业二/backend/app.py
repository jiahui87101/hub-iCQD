"""FastAPI 服务入口。

接口：
- GET  /health                       健康检查
- POST /api/research                 提交研究（topic），返回 research_id
- GET  /api/research                 列出最近 N 条记录
- GET  /api/research/{rid}           查一条记录（含中间结果）
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import APP_PORT
from .models import ResearchCreated, ResearchRecord, ResearchRequest
from .research import ResearchService, launch

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.info("backend starting on port %d", APP_PORT)
    yield
    logger.info("backend shutting down")


app = FastAPI(title="深度研究助手", version="0.1.0", lifespan=lifespan)

# CORS：允许本地前端（Next.js dev 跑在 3000）跨域调
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/research", response_model=ResearchCreated, status_code=202)
async def submit_research(body: ResearchRequest) -> ResearchCreated:
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic 不能为空")
    rec = ResearchService.submit(topic)
    # 启动后台任务
    launch(rec.id)
    return ResearchCreated(research_id=rec.id)


@app.get("/api/research", response_model=list[ResearchRecord])
async def list_research() -> list[ResearchRecord]:
    return ResearchService.list_recent(limit=50)


@app.get("/api/research/{rid}", response_model=ResearchRecord)
async def get_research(rid: str) -> ResearchRecord:
    rec = ResearchService.get(rid)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"research {rid} not found")
    return rec


if __name__ == "__main__":
    # 打印路由 + 起开发服务器
    import uvicorn

    print("routes:")
    for r in app.routes:
        if hasattr(r, "methods"):
            print(f"  {','.join(sorted(r.methods))} {r.path}")

    uvicorn.run("backend.app:app", host="0.0.0.0", port=APP_PORT, reload=False)
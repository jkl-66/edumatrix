"""任务 7.6: 一键导出学情诊断与能力对齐PDF报告

核心设计：
1. BrowserPool — FastAPI 全局初始化浏览器池，asyncio.Semaphore(3) 限流
2. Playwright 无头浏览器渲染 A4 PDF，保留背景图表
3. 专用 Print-only 页面排版
4. StreamingResponse 流式返回

接口：
    GET /api/v1/profile/export?student_id=xxx
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.crud import load_student_profile
from app.database import get_db
from app.auth import enforce_request_student_scope, enforce_student_access, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/profile", tags=["profile"], dependencies=[Depends(enforce_request_student_scope)])


# ============================================================
# BrowserPool — Playwright 无头浏览器并发安全池
# ============================================================

class BrowserPool:
    """高并发渲染安全池。

    通过 asyncio.Semaphore(3) 限制最大并发渲染数，
    单任务渲染超时限制 10 秒。
    """

    def __init__(self, max_concurrent: int = 3, render_timeout: int = 10):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.render_timeout = render_timeout
        self._browser = None
        self._lock = asyncio.Lock()

    async def get_browser(self):
        """惰性初始化浏览器实例。"""
        if self._browser is None:
            async with self._lock:
                if self._browser is None:
                    try:
                        from playwright.async_api import async_playwright
                        p = await async_playwright().start()
                        self._browser = await p.chromium.launch(
                            headless=True,
                            args=["--no-sandbox", "--disable-gpu"],
                        )
                        logger.info("BrowserPool: Playwright 浏览器启动成功")
                    except Exception as e:
                        logger.error(f"BrowserPool: 浏览器启动失败: {e}")
                        raise
        return self._browser

    async def render_pdf(self, html: str) -> bytes:
        """渲染 HTML 为 A4 PDF。

        Args:
            html: 完整的 HTML 文档字符串

        Returns:
            PDF 字节流
        """
        async with self.semaphore:
            browser = await self.get_browser()
            page = await browser.new_page()
            try:
                await page.set_content(html, timeout=self.render_timeout * 1000)
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={"top": "15mm", "bottom": "15mm", "left": "15mm", "right": "15mm"},
                )
                return pdf_bytes
            except Exception as e:
                logger.error(f"BrowserPool: PDF 渲染失败: {e}")
                # 降级：返回纯文本 PDF 描述
                fallback_html = f"""<html><body>
                <h1>EduMatrix 学情报告 (降级版)</h1>
                <p>PDF 渲染异常: {e}</p>
                <pre>{html[:2000]}</pre>
                </body></html>"""
                page = await browser.new_page()
                await page.set_content(fallback_html)
                return await page.pdf(format="A4", print_background=True)
            finally:
                await page.close()

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = None


# 全局浏览器池单例
_browser_pool: BrowserPool | None = None


async def get_browser_pool() -> BrowserPool:
    global _browser_pool
    if _browser_pool is None:
        _browser_pool = BrowserPool(max_concurrent=3, render_timeout=10)
    return _browser_pool


# ============================================================
# HTML 报告模板
# ============================================================

def _build_report_html(profile: Any) -> str:
    """生成标准化学情诊断报告 HTML (Print-only 排版)。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    mastery_data = json.dumps(
        [{"name": k, "value": round(v * 100, 1)} for k, v in (profile.concept_mastery or {}).items()]
    )
    cause_data = json.dumps(
        [{"name": k, "value": round(v.percentage, 1)} for k, v in (profile.learning_state_causes or {}).items()]
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8">
<style>
    @page {{ margin: 15mm; }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; color: #1e293b; padding: 20px; }}
    h1 {{ color: #4f46e5; font-size: 22px; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; }}
    h2 {{ color: #334155; font-size: 16px; margin-top: 24px; }}
    .meta {{ color: #64748b; font-size: 12px; margin-bottom: 16px; }}
    .grid {{ display: flex; gap: 16px; flex-wrap: wrap; }}
    .card {{ border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; flex: 1; min-width: 180px; }}
    .card h3 {{ margin: 0 0 8px; font-size: 13px; color: #64748b; }}
    .card .value {{ font-size: 24px; font-weight: bold; color: #4f46e5; }}
    .card .sub {{ font-size: 11px; color: #94a3b8; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 12px; }}
    th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #e2e8f0; }}
    th {{ background: #f1f5f9; color: #475569; font-weight: 600; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 10px; }}
    .badge-green {{ background: #dcfce7; color: #166534; }}
    .badge-yellow {{ background: #fef9c3; color: #854d0e; }}
    .badge-red {{ background: #fee2e2; color: #991b1b; }}
    .chart-container {{ margin: 16px 0; text-align: center; }}
    .progress-bar {{ height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; margin: 4px 0; }}
    .progress-fill {{ height: 100%; border-radius: 4px; }}
    .footer {{ margin-top: 24px; padding-top: 12px; border-top: 1px solid #e2e8f0; font-size: 10px; color: #94a3b8; text-align: center; }}
</style></head><body>

<h1>EduMatrix 学情诊断报告</h1>
<div class="meta">学生 ID: {profile.student_id} | 生成时间: {now}</div>

<!-- 概览卡片 -->
<div class="grid">
    <div class="card">
        <h3>综合掌握度</h3>
        <div class="value">{round((profile.mastery_score or 0) * 100, 1)}%</div>
        <div class="sub">总知识点: {len(profile.concept_mastery or {})}</div>
    </div>
    <div class="card">
        <h3>认知负荷</h3>
        <div class="value">{round((profile.cognitive_load or 0) * 100, 1)}%</div>
        <div class="sub">专注度: {round((profile.focus_level or 0) * 100, 1)}%</div>
    </div>
    <div class="card">
        <h3>学习风格</h3>
        <div class="value" style="font-size:18px">{profile.learning_style or '未诊断'}</div>
        <div class="sub">动机: {profile.motivation_type or '未诊断'}</div>
    </div>
    <div class="card">
        <h3>学习交互</h3>
        <div class="value">{profile.session_interactions or 0}</div>
        <div class="sub">会话交互次数</div>
    </div>
</div>

<h2>知识点掌握度</h2>
<table>
    <tr><th>知识点</th><th>掌握度</th><th>掌握状态</th></tr>
    {''.join(f'<tr><td>{k}</td><td>{round(v*100,1)}%</td>'
             f'<td><span class="badge {"badge-green" if v>=0.7 else "badge-yellow" if v>=0.3 else "badge-red"}">'
             f'{"已掌握" if v>=0.7 else "发展中" if v>=0.3 else "薄弱"}</span></td></tr>'
             for k, v in sorted((profile.concept_mastery or {}).items(), key=lambda x: -x[1]))}
</table>

<h2>薄弱知识点</h2>
<p>{', '.join(profile.weak_points) if profile.weak_points else '暂无薄弱知识点'}</p>

<h2>学习状态归因</h2>
<table>
    <tr><th>归因类型</th><th>占比</th></tr>
    {''.join(f'<tr><td>{v.label}</td><td>{round(v.percentage,1)}%</td></tr>'
             for v in (profile.learning_state_causes or {}).values())}
</table>

<h2>AI 学习建议</h2>
<ul>
    <li>基于当前掌握度，建议优先巩固薄弱知识点</li>
    <li>推荐学习风格匹配的教学策略</li>
    <li>关注认知负荷与专注度变化趋势</li>
</ul>

<div class="footer">
    EduMatrix 智教矩阵 · 智能自适应教育系统 · {now}
</div>

</body></html>"""
    return html


# ============================================================
# 导出接口
# ============================================================


@router.get("/export")
async def export_profile_pdf(
    student_id: str = Query("default", description="学生 ID"),
    db: Session = Depends(get_db),
    pool: BrowserPool = Depends(get_browser_pool),
    current_user=Depends(get_current_user),
):
    """导出学生画像为 PDF 诊断报告。

    流程：
    1. 加载学生画像数据
    2. 生成 Print-only HTML
    3. Playwright 无头浏览器渲染 A4 PDF
    4. StreamingResponse 流式返回
    """
    student_id = enforce_student_access(student_id, current_user)
    profile = load_student_profile(db, student_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学生画像未找到")

    try:
        html = _build_report_html(profile)
        pdf_bytes = await pool.render_pdf(html)

        filename = f"EduMatrix_学情报告_{student_id}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf"

        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(pdf_bytes)),
            },
        )
    except Exception as e:
        logger.error(f"PDF 导出失败: {e}")
        raise HTTPException(status_code=500, detail=f"PDF 生成失败: {e}")

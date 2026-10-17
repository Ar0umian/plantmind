from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from agent.engine import Engine
from agent.report_generator import render_html

router = APIRouter(tags=["reports"])


def _engine(request: Request) -> Engine:
    return request.app.state.engine


def _bundle(request: Request, alert_id: str):
    bundle = _engine(request).incident_report_bundle(alert_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return bundle


@router.get("/alerts/{alert_id}/report")
def report_json(alert_id: str, request: Request):
    return _bundle(request, alert_id).report


@router.get("/alerts/{alert_id}/report.md")
def report_markdown(alert_id: str, request: Request, download: bool = Query(False)):
    bundle = _bundle(request, alert_id)
    headers = {"Content-Disposition": f'attachment; filename="incident-{alert_id}.md"'} if download else {}
    return Response(content=bundle.report.markdown, media_type="text/markdown; charset=utf-8", headers=headers)


@router.get("/alerts/{alert_id}/report.html")
def report_html(alert_id: str, request: Request, download: bool = Query(False)):
    bundle = _bundle(request, alert_id)
    headers = {"Content-Disposition": f'attachment; filename="incident-{alert_id}.html"'} if download else {}
    return HTMLResponse(content=render_html(bundle), headers=headers)

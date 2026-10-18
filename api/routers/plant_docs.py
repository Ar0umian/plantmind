from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response

from agent.engine import Engine

router = APIRouter(tags=["plant-document"])


def _engine(request: Request) -> Engine:
    return request.app.state.engine


@router.get("/docs/plant")
def plant_document(request: Request):
    return _engine(request).plant_document()


@router.get("/docs/plant.md")
def plant_markdown(request: Request, download: bool = Query(False)):
    doc = _engine(request).plant_document()
    headers = {"Content-Disposition": 'attachment; filename="plant-operating-document.md"'} if download else {}
    return Response(content=doc.markdown, media_type="text/markdown; charset=utf-8", headers=headers)


@router.get("/docs/plant.html")
def plant_html(request: Request, download: bool = Query(False)):
    doc = _engine(request).plant_document()
    headers = {"Content-Disposition": 'attachment; filename="plant-operating-document.html"'} if download else {}
    return HTMLResponse(content=doc.html, headers=headers)

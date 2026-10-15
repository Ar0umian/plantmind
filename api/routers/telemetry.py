from fastapi import APIRouter, Query, Request

from agent.engine import Engine
from core.contracts import CONTRACT_VERSION

router = APIRouter(tags=["telemetry"])


def _engine(request: Request) -> Engine:
    return request.app.state.engine


@router.get("/state")
def state(request: Request):
    engine = _engine(request)
    return {
        "contract_version": CONTRACT_VERSION,
        "latest": engine.latest_frame(),
        "demo_scenario": engine.demo_scenario,      # ground truth, for the demo panel only
        "active_evidence": engine.active_evidence(),
    }


@router.get("/telemetry")
def telemetry(request: Request, n: int = Query(120, ge=1, le=3600)):
    return _engine(request).frames(n)


@router.get("/evidence")
def evidence(request: Request):
    return _engine(request).history()


@router.get("/knowledge-map")
def knowledge_map(request: Request):
    return _engine(request).kmap

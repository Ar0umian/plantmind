from fastapi import APIRouter, HTTPException, Request

from agent.engine import Engine

router = APIRouter(tags=["scenarios"])


def _engine(request: Request) -> Engine:
    return request.app.state.engine


@router.get("/scenarios")
def list_scenarios(request: Request):
    return _engine(request).scenarios()


@router.post("/scenarios/stop")
def stop_scenario(request: Request):
    _engine(request).stop_scenario()
    return {"scenario": "normal"}


@router.post("/scenarios/{name}/start")
def start_scenario(name: str, request: Request):
    engine = _engine(request)
    if name not in [s["name"] for s in engine.scenarios()]:
        raise HTTPException(status_code=404, detail="unknown scenario")
    engine.start_scenario(name)
    return {"scenario": name}


@router.post("/demo/reset")
def reset_demo(request: Request):
    _engine(request).reset_detection()
    return {"status": "reset"}

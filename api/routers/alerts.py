from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agent.engine import Engine

router = APIRouter(tags=["alerts"])


class DecisionBody(BaseModel):
    decision: Literal["approved", "rejected", "deferred"]


def _engine(request: Request) -> Engine:
    return request.app.state.engine


@router.get("/alerts")
def list_alerts(request: Request):
    return _engine(request).alerts()


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: str, request: Request):
    alert = _engine(request).get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return alert


@router.post("/alerts/{alert_id}/decision")
def decide(alert_id: str, body: DecisionBody, request: Request):
    try:
        return _engine(request).decide(alert_id, body.decision)
    except KeyError:
        raise HTTPException(status_code=404, detail="alert not found")


@router.get("/decisions")
def decisions(request: Request):
    return _engine(request).decisions()

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent.engine import APPROVED_PROGRAM, PROGRAMS, Engine

router = APIRouter(tags=["change-guard"])


class CheckBody(BaseModel):
    candidate: str = Field(min_length=1, max_length=200_000)     # NFR-SEC-03: bounded input
    label: str = Field(default="uploaded program", max_length=80)


class GuardDecisionBody(BaseModel):
    decision: Literal["approved", "rejected", "needs_review"]


def _engine(request: Request) -> Engine:
    return request.app.state.engine


@router.post("/guard/check")
def check(body: CheckBody, request: Request):
    """Compares a candidate program (text only, never executed) with the approved one."""
    return _engine(request).guard.check(body.candidate, source=body.label)


@router.get("/guard/reports")
def reports(request: Request):
    return _engine(request).guard.results()


@router.get("/guard/running")
def running(request: Request):
    result = _engine(request).guard_running()
    return {"matches_approved": result is None, "result": result}


@router.get("/guard/samples")
def samples():
    return {"approved": APPROVED_PROGRAM.read_text(encoding="utf-8"),
            "tampered": PROGRAMS["tampered"].read_text(encoding="utf-8")}


@router.post("/guard/{candidate_hash}/decision")
def decide(candidate_hash: str, body: GuardDecisionBody, request: Request):
    try:
        return _engine(request).guard.decide(candidate_hash, body.decision)
    except KeyError:
        raise HTTPException(status_code=404, detail="report not found")

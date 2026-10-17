from typing import List, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from agent.engine import Engine

router = APIRouter(tags=["assistant"])


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=500)


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)      # NFR-SEC-03: bounded input
    history: List[Turn] = Field(default_factory=list, max_length=12)


def _engine(request: Request) -> Engine:
    return request.app.state.engine


@router.post("/assistant/ask")
def ask(body: AskBody, request: Request):
    """Advisory Q&A grounded in the approved logic and the live state. Never acts on equipment."""
    history = [{"role": t.role, "text": t.text} for t in body.history]
    return _engine(request).ask(body.question, history)

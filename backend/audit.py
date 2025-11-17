from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from typing import Any

audit_logger = logging.getLogger("backend.audit")
_actor: ContextVar[str] = ContextVar("audit_actor", default="anonymous")


def bind_actor(actor_id: str | None) -> Token:
    """Bind the current actor for downstream logging."""
    return _actor.set(actor_id or "anonymous")


def reset_actor(token: Token) -> None:
    """Restore the previous actor binding."""
    try:
        _actor.reset(token)
    except LookupError:
        pass


def current_actor() -> str:
    return _actor.get()


def log_meeting_access(action: str, *, meeting_id: str | None = None, resource: str = "meeting", details: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "event": "meeting_data_access",
        "actor": current_actor(),
        "action": action,
        "resource": resource,
    }
    if meeting_id:
        payload["meeting_id"] = meeting_id
    if details:
        payload.update(details)
    audit_logger.info("meeting_data_access", extra={"audit": payload})


def log_mlflow_access(action: str, *, meeting_id: str, run_id: str | None = None, details: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "event": "mlflow_access",
        "actor": current_actor(),
        "action": action,
        "meeting_id": meeting_id,
    }
    if run_id:
        payload["run_id"] = run_id
    if details:
        payload.update(details)
    audit_logger.info("mlflow_access", extra={"audit": payload})

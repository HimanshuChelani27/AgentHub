"""Spans stored in the database, grouped by run. Callers pass run_id / parent_id explicitly
(the crew sends them as headers), which keeps tracing simple and visible in the API."""

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.models import Span


def record_span(
    session: Session,
    *,
    name: str,
    kind: str,
    start: datetime,
    run_id: str | None = None,
    parent_id: str | None = None,
    status: str = "ok",
    attrs: dict[str, Any] | None = None,
    end: datetime | None = None,
) -> Span:
    span = Span(
        run_id=run_id,
        parent_id=parent_id,
        name=name,
        kind=kind,
        status=status,
        start=start,
        end=end or datetime.now(UTC),
        attrs=attrs or {},
    )
    session.add(span)
    return span

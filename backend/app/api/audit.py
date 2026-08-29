"""
GET /api/audit and GET /api/audit/{transaction_id}.

Read-only projection of persisted AuditLog rows. The frontend cannot
fabricate, edit, or reorder audit events - it can only display what the
backend already wrote during a recover_transaction() call.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas import AuditEventOut
from app.db import repository
from app.db.session import get_db

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _to_out(row, txn_id) -> AuditEventOut:
    return AuditEventOut(
        timestamp=_iso(row.timestamp),
        event_type=row.event_type,
        transaction_id=txn_id,
        requested_action=row.requested_action,
        rules_decision=row.rules_decision,
        execution_status=row.execution_status,
        reason_codes=json.loads(row.reason_codes) if row.reason_codes else [],
        explanation=row.explanation or row.event_detail,
    )


@router.get("", response_model=list[AuditEventOut])
def list_all_audit_events(
    limit: int = Query(default=200, ge=1, le=1000), db: Session = Depends(get_db)
) -> list[AuditEventOut]:
    rows = repository.list_audit_events(db, transaction_id=None, limit=limit)
    return [_to_out(row, txn_id) for row, txn_id in rows]


@router.get("/{transaction_id}", response_model=list[AuditEventOut])
def get_audit_trail_for_transaction(transaction_id: str, db: Session = Depends(get_db)) -> list[AuditEventOut]:
    rows = repository.list_audit_events(db, transaction_id=transaction_id)
    return [_to_out(row, txn_id) for row, txn_id in reversed(rows)]  # chronological

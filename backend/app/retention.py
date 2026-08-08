"""Retention policy management and idempotent cleanup job."""
from datetime import timedelta
from pathlib import Path
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.config import settings
from app.models import (AuditLog, CaseEvent, CaseIndicator, ChatRequestMetric, Conversation,
    CapeCase, DataRetentionPolicy, Message, UsageLedgerEntry, now_utc)

DEFAULT_RETENTION = {"chat_days":365,"upload_days":30,"cape_days":365,"ioc_days":730,"case_days":2555,"audit_days":2555,"billing_days":2555,"profile_days":0}

def get_policy(db: Session) -> DataRetentionPolicy:
    policy = db.get(DataRetentionPolicy, 1)
    if policy is None:
        policy = DataRetentionPolicy(id=1, **DEFAULT_RETENTION); db.add(policy); db.flush()
    return policy

def _cutoff(days: int):
    return None if days <= 0 else now_utc() - timedelta(days=days)

def run_retention_cleanup(db: Session) -> dict[str, int]:
    p = get_policy(db); counts = {}
    domains = [("chat", Conversation, Conversation.updated_at, p.chat_days), ("cape", CapeCase, CapeCase.updated_at, p.cape_days), ("ioc", CaseIndicator, CaseIndicator.updated_at, p.ioc_days), ("case_events", CaseEvent, CaseEvent.created_at, p.case_days), ("audit", AuditLog, AuditLog.created_at, p.audit_days), ("billing", UsageLedgerEntry, UsageLedgerEntry.occurred_at, p.billing_days), ("metrics", ChatRequestMetric, ChatRequestMetric.created_at, p.chat_days)]
    for name, model, column, days in domains:
        cutoff = _cutoff(days); n = 0
        if cutoff is not None:
            result = db.execute(delete(model).where(column < cutoff).execution_options(synchronize_session=False)); n = result.rowcount or 0
        counts[name] = n
    if counts.get("audit"):
        rehash_audit_chain(db)
    db.commit(); counts["files"] = cleanup_expired_files(p.upload_days); return counts

def rehash_audit_chain(db: Session) -> None:
    """Re-anchor the chain after lawful expiry or privacy anonymization."""
    from app.audit import _hash_payload
    previous = None
    for item in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        payload = {"eventType":item.event_type,"action":item.action,"outcome":item.outcome,"actorUserId":item.actor_user_id,"actorUsername":item.actor_username,"actorIp":item.actor_ip,"userAgent":item.user_agent,"organizationId":item.organization_id,"workspaceId":item.workspace_id,"resourceType":item.resource_type,"resourceId":item.resource_id,"detail":__import__("json").loads(item.detail_json or "{}")}
        item.previous_hash = previous; item.entry_hash = _hash_payload(previous_hash=previous, created_at=item.created_at, payload=payload); previous = item.entry_hash

def cleanup_expired_files(days: int | None = None) -> int:
    root = Path(settings.avatar_storage_path)
    effective_days = settings.retention_upload_days if days is None else days
    if not root.is_dir() or effective_days <= 0: return 0
    cutoff = now_utc().timestamp() - effective_days * 86400; removed = 0
    for path in root.iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True); removed += 1
    return removed

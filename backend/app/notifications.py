from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notification, NotificationPreference, OrganizationMember

NOTIFICATION_TYPES = (
    "cape_completed", "model_failed", "mention", "sla_warning", "quota_low",
    "subscription_expiring", "threat_intel_updated", "case_shared", "case_comment", "case_assigned",
)


@dataclass(frozen=True)
class NotificationEvent:
    organization_id: int
    user_id: int
    notification_type: str
    title: str
    idempotency_key: str
    body: str | None = None
    actor_user_id: int | None = None
    case_id: int | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    resource_url: str | None = None


class NotificationChannel(Protocol):
    name: str

    def deliver(self, db: Session, event: NotificationEvent) -> None: ...


class InAppNotificationChannel:
    name = "in_app"

    def deliver(self, db: Session, event: NotificationEvent) -> None:
        pending = any(
            isinstance(item, Notification)
            and item.organization_id == event.organization_id
            and item.user_id == event.user_id
            and item.idempotency_key == event.idempotency_key
            for item in db.new
        )
        if pending:
            return
        existing = db.execute(select(Notification.id).where(
            Notification.organization_id == event.organization_id,
            Notification.user_id == event.user_id,
            Notification.idempotency_key == event.idempotency_key,
        )).scalar_one_or_none()
        if existing is not None:
            return
        db.add(Notification(
            organization_id=event.organization_id, user_id=event.user_id,
            notification_type=event.notification_type, title=event.title, body=event.body,
            actor_user_id=event.actor_user_id, case_id=event.case_id,
            resource_type=event.resource_type, resource_id=event.resource_id,
            resource_url=event.resource_url, idempotency_key=event.idempotency_key,
        ))


class EmailNotificationChannel:
    name = "email"

    def deliver(self, db: Session, event: NotificationEvent) -> None:
        return None


class WebPushNotificationChannel:
    name = "web_push"

    def deliver(self, db: Session, event: NotificationEvent) -> None:
        return None


CHANNELS: tuple[NotificationChannel, ...] = (
    InAppNotificationChannel(), EmailNotificationChannel(), WebPushNotificationChannel(),
)


def notify(db: Session, event: NotificationEvent) -> bool:
    if event.notification_type not in NOTIFICATION_TYPES:
        raise ValueError(f"Unsupported notification type: {event.notification_type}")
    membership = db.execute(select(OrganizationMember.id).where(
        OrganizationMember.organization_id == event.organization_id,
        OrganizationMember.user_id == event.user_id,
    )).scalar_one_or_none()
    if membership is None:
        return False
    preference = db.execute(select(NotificationPreference).where(
        NotificationPreference.organization_id == event.organization_id,
        NotificationPreference.user_id == event.user_id,
        NotificationPreference.notification_type == event.notification_type,
    )).scalar_one_or_none()
    enabled = {
        "in_app": preference is None or preference.in_app_enabled,
        "email": preference is not None and preference.email_enabled,
        "web_push": preference is not None and preference.web_push_enabled,
    }
    for channel in CHANNELS:
        if enabled[channel.name]:
            channel.deliver(db, event)
    return True

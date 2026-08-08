from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Conversation, Message, MessageEvidence, Session as SessionModel, User
from app.routes.chat import persist_conversation_messages
from app.routes.conversations import update_conversation
from app.schemas import ConversationUpdate


def build_session() -> tuple[Session, SessionModel, Conversation]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(username="analyst", password_hash="unused")
    db.add(user)
    db.flush()
    current_session = SessionModel(
        user_id=user.id,
        token_hash="a" * 64,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(current_session)
    db.flush()
    conversation = Conversation(
        owner_session_id=current_session.id,
        owner_user_id=user.id,
        title="Incident 42",
    )
    db.add(conversation)
    db.commit()
    db.refresh(current_session)
    db.refresh(conversation)
    return db, current_session, conversation


def test_case_metadata_update_persists_structured_fields() -> None:
    db, current_session, conversation = build_session()
    try:
        updated = update_conversation(
            conversation.id,
            ConversationUpdate(
                caseStatus="investigating",
                severity="critical",
                assignee="SOC lead",
                tags=["ransomware", "priority"],
                caseSummary="Encryption behavior confirmed.",
            ),
            current_session,
            db,
        )

        assert updated.case_status == "investigating"
        assert updated.severity == "critical"
        assert updated.tags == ["ransomware", "priority"]
        assert updated.case_summary == "Encryption behavior confirmed."
    finally:
        db.close()


def test_assistant_evidence_is_persisted_with_the_answer() -> None:
    db, current_session, conversation = build_session()
    try:
        persist_conversation_messages(
            db,
            current_session=current_session,
            conversation_id=str(conversation.id),
            user_message_content="Check this advisory",
            user_attachments=[],
            assistant_content="The indicator is malicious [W1].",
            assistant_evidence=[
                {
                    "sourceType": "web",
                    "citation": "W1",
                    "title": "Threat advisory",
                    "url": "https://example.test/advisory",
                    "locator": "Search result 1",
                    "snippet": "Known malicious infrastructure",
                }
            ],
        )

        assistant = db.execute(
            select(Message).where(Message.role == "assistant")
        ).scalar_one()
        evidence = db.execute(
            select(MessageEvidence).where(MessageEvidence.message_id == assistant.id)
        ).scalar_one()
        assert evidence.citation == "W1"
        assert evidence.source_type == "web"
        assert evidence.url == "https://example.test/advisory"
    finally:
        db.close()

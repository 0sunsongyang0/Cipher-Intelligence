import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import require_user_session
from app.database import get_db
from app.models import Conversation, Message, MessageAttachment, Session as SessionModel
from app.schemas import (
    ConversationCreate,
    ConversationImportRequest,
    ConversationImportResult,
    ConversationItem,
    ConversationList,
    ConversationUpdate,
    MessageList,
)
from app.analysis_templates import resolve_template


router = APIRouter(
    prefix="/api/conversations",
    tags=["conversations"],
)


def get_owned_conversation(
    db: Session, conversation_id: int, current_session: SessionModel
) -> Conversation | None:
    return db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.owner_user_id == current_session.user_id,
        )
    ).scalar_one_or_none()


@router.get("", response_model=ConversationList)
def list_conversations(
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> ConversationList:
    conversations = db.execute(
        select(Conversation)
        .where(Conversation.owner_user_id == current_session.user_id)
        .order_by(
            Conversation.is_pinned.desc(),
            Conversation.updated_at.desc(),
            Conversation.id.desc(),
        )
    ).scalars().all()
    return ConversationList(items=conversations)


@router.post("", response_model=ConversationItem, status_code=status.HTTP_201_CREATED)
def create_conversation(
    conversation: ConversationCreate,
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> Conversation:
    template, config = resolve_template(db, conversation.templateId, current_session.user_id)
    db_conversation = Conversation(
        title=conversation.title,
        owner_session_id=current_session.id,
        owner_user_id=current_session.user_id,
        analysis_template_id=template.id if template else None,
        analysis_template_version=template.current_version if template else None,
        analysis_config_json=json.dumps(config, ensure_ascii=False) if config else None,
    )
    db.add(db_conversation)
    db.commit()
    db.refresh(db_conversation)
    return db_conversation


@router.post("/import", response_model=ConversationImportResult, status_code=status.HTTP_201_CREATED)
def import_conversation(
    payload: ConversationImportRequest,
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> ConversationImportResult:
    db_conversation = Conversation(
        title=payload.title,
        owner_session_id=current_session.id,
        owner_user_id=current_session.user_id,
    )
    db.add(db_conversation)
    db.flush()

    for message in payload.messages:
        db_message = Message(
            conversation_id=db_conversation.id,
            role=message.role,
            content=message.content,
        )
        db.add(db_message)
        db.flush()

        for attachment in message.attachments:
            db.add(
                MessageAttachment(
                    message_id=db_message.id,
                    attachment_id=attachment.id,
                    name=attachment.name,
                    type=attachment.type,
                    size=attachment.size,
                    meta=attachment.meta,
                )
            )

    db.commit()
    db.refresh(db_conversation)

    return ConversationImportResult(
        id=db_conversation.id,
        title=db_conversation.title,
        is_pinned=db_conversation.is_pinned,
        is_archived=db_conversation.is_archived,
        case_status=db_conversation.case_status,
        severity=db_conversation.severity,
        assignee=db_conversation.assignee,
        tags=db_conversation.tags,
        case_summary=db_conversation.case_summary,
        created_at=db_conversation.created_at,
        updated_at=db_conversation.updated_at,
        importedMessages=len(payload.messages),
    )


@router.get("/{conversation_id}/messages", response_model=MessageList)
def list_messages(
    conversation_id: int,
    limit: int | None = Query(default=None, ge=1, le=200),
    before: int | None = Query(default=None, ge=1),
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> MessageList:
    conversation = get_owned_conversation(db, conversation_id, current_session)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    query = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .options(selectinload(Message.attachments), selectinload(Message.evidence))
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    if limit is None and before is None:
        return MessageList(items=db.execute(query).scalars().all())

    total = db.scalar(select(func.count(Message.id)).where(Message.conversation_id == conversation_id)) or 0
    paged_query = select(Message).where(Message.conversation_id == conversation_id)
    if before is not None:
        paged_query = paged_query.where(Message.id < before)
    messages = list(db.execute(
        paged_query.options(selectinload(Message.attachments), selectinload(Message.evidence))
        .order_by(Message.id.desc()).limit(limit or 60)
    ).scalars().all())
    messages.reverse()
    return MessageList(items=messages, nextCursor=messages[0].id if messages and messages[0].id > 1 else None, total=total)


@router.patch("/{conversation_id}", response_model=ConversationItem)
def update_conversation(
    conversation_id: int,
    payload: ConversationUpdate,
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> Conversation:
    conversation = get_owned_conversation(db, conversation_id, current_session)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    if payload.title is not None:
        conversation.title = payload.title
    if payload.isPinned is not None:
        conversation.is_pinned = payload.isPinned
    if payload.isArchived is not None:
        conversation.is_archived = payload.isArchived
        if payload.isArchived:
            conversation.is_pinned = False
    if payload.caseStatus is not None:
        conversation.case_status = payload.caseStatus
    if payload.severity is not None:
        conversation.severity = payload.severity
    if payload.assignee is not None:
        conversation.assignee = payload.assignee or None
    if payload.tags is not None:
        conversation.tags_json = json.dumps(payload.tags, ensure_ascii=False)
    if payload.caseSummary is not None:
        conversation.case_summary = payload.caseSummary or None

    db.commit()
    db.refresh(conversation)
    return conversation


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: int,
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> Response:
    conversation = get_owned_conversation(db, conversation_id, current_session)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    db.delete(conversation)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

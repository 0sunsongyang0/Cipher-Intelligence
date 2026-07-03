from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_session
from app.database import get_db
from app.models import Conversation, Message, Session as SessionModel
from app.schemas import ConversationCreate, ConversationItem, ConversationList, MessageList


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
            Conversation.owner_session_id == current_session.id,
        )
    ).scalar_one_or_none()


@router.get("", response_model=ConversationList)
def list_conversations(
    current_session: SessionModel = Depends(require_session),
    db: Session = Depends(get_db),
) -> ConversationList:
    conversations = db.execute(
        select(Conversation)
        .where(Conversation.owner_session_id == current_session.id)
        .order_by(Conversation.created_at.desc(), Conversation.id.desc())
    ).scalars().all()
    return ConversationList(items=conversations)


@router.post("", response_model=ConversationItem, status_code=status.HTTP_201_CREATED)
def create_conversation(
    conversation: ConversationCreate,
    current_session: SessionModel = Depends(require_session),
    db: Session = Depends(get_db),
) -> Conversation:
    db_conversation = Conversation(title=conversation.title, owner_session_id=current_session.id)
    db.add(db_conversation)
    db.commit()
    db.refresh(db_conversation)
    return db_conversation


@router.get("/{conversation_id}/messages", response_model=MessageList)
def list_messages(
    conversation_id: int,
    current_session: SessionModel = Depends(require_session),
    db: Session = Depends(get_db),
) -> MessageList:
    conversation = get_owned_conversation(db, conversation_id, current_session)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    messages = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).scalars().all()
    return MessageList(items=messages)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: int,
    current_session: SessionModel = Depends(require_session),
    db: Session = Depends(get_db),
) -> Response:
    conversation = get_owned_conversation(db, conversation_id, current_session)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    db.delete(conversation)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.database import Base, engine, get_db
from app.models import Conversation
from app.schemas import ConversationCreate, ConversationItem, ConversationList


Base.metadata.create_all(bind=engine)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=ConversationList)
def list_conversations(db: Session = Depends(get_db)) -> ConversationList:
    conversations = db.execute(
        select(Conversation).order_by(Conversation.created_at.desc(), Conversation.id.desc())
    ).scalars().all()
    return ConversationList(items=conversations)


@router.post("", response_model=ConversationItem, status_code=status.HTTP_201_CREATED)
def create_conversation(
    conversation: ConversationCreate, db: Session = Depends(get_db)
) -> Conversation:
    db_conversation = Conversation(title=conversation.title)
    db.add(db_conversation)
    db.commit()
    db.refresh(db_conversation)
    return db_conversation


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)) -> Response:
    conversation = db.get(Conversation, conversation_id)
    if conversation is not None:
        db.delete(conversation)
        db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)

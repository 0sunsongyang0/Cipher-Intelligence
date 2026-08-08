from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_user_session
from app.database import get_db
from app.models import Conversation, Message, MessageFeedback, Session as SessionModel, now_utc
from app.schemas import MessageFeedbackRequest, MessageFeedbackResponse


router = APIRouter(prefix="/api/messages", tags=["feedback"])


@router.put("/{message_id}/feedback", response_model=MessageFeedbackResponse)
def update_message_feedback(
    message_id: int,
    payload: MessageFeedbackRequest,
    current_session: SessionModel = Depends(require_user_session),
    db: Session = Depends(get_db),
) -> MessageFeedbackResponse:
    message = db.execute(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.id == message_id,
            Message.role == "assistant",
            Conversation.owner_user_id == current_session.user_id,
        )
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    feedback = db.execute(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message_id,
            MessageFeedback.user_id == current_session.user_id,
        )
    ).scalar_one_or_none()

    if payload.rating is None:
        if feedback is not None:
            db.delete(feedback)
        db.commit()
        return MessageFeedbackResponse(messageId=message_id, rating=None, reason=None)

    if feedback is None:
        feedback = MessageFeedback(
            message_id=message_id,
            user_id=current_session.user_id,
            rating=payload.rating,
        )
        db.add(feedback)
    else:
        feedback.rating = payload.rating

    feedback.reason = payload.reason if payload.rating == "down" else None
    feedback.note = payload.note if payload.rating == "down" else None
    feedback.updated_at = now_utc()
    db.commit()
    return MessageFeedbackResponse(
        messageId=message_id,
        rating=feedback.rating,
        reason=feedback.reason,
    )

from sqlalchemy.orm import Session

from app.models.feedback import LeadFeedback
from app.schemas.feedback import FeedbackRequest


def create_feedback(db: Session, payload: FeedbackRequest) -> LeadFeedback:
    feedback = LeadFeedback(
        company_id=payload.company_id,
        action=payload.action,
        user_name=payload.user_name,
        query_text=payload.query_text,
        note=payload.note,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback

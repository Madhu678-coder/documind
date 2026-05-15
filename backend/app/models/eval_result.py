import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_messages.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    faithfulness_score: Mapped[float]
    faithfulness_reason: Mapped[str]
    answer_relevancy_score: Mapped[float]
    contextual_precision_score: Mapped[float]
    contextual_recall_score: Mapped[float]
    hallucination_score: Mapped[float]
    overall_pass: Mapped[bool]
    eval_model: Mapped[str]
    triggered_by: Mapped[str]
    evaluated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

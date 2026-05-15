import uuid
from sqlalchemy import Boolean, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class EvalConfig(Base):
    __tablename__ = "eval_config"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), unique=True)
    faithfulness_threshold: Mapped[float] = mapped_column(default=0.85)
    answer_relevancy_threshold: Mapped[float] = mapped_column(default=0.80)
    contextual_precision_threshold: Mapped[float] = mapped_column(default=0.75)
    contextual_recall_threshold: Mapped[float] = mapped_column(default=0.75)
    hallucination_threshold: Mapped[float] = mapped_column(default=0.15)
    multi_turn_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

"""DeepEval metric definitions with default thresholds per Requirements 13.4."""
from __future__ import annotations

from dataclasses import dataclass

# Default thresholds (Requirements 13.4, 13.7)
DEFAULT_FAITHFULNESS_THRESHOLD: float = 0.85
DEFAULT_ANSWER_RELEVANCY_THRESHOLD: float = 0.80
DEFAULT_CONTEXTUAL_PRECISION_THRESHOLD: float = 0.75
DEFAULT_CONTEXTUAL_RECALL_THRESHOLD: float = 0.75
DEFAULT_HALLUCINATION_THRESHOLD: float = 0.15


@dataclass
class EvalThresholds:
    """Workspace-level evaluation thresholds."""
    faithfulness: float = DEFAULT_FAITHFULNESS_THRESHOLD
    answer_relevancy: float = DEFAULT_ANSWER_RELEVANCY_THRESHOLD
    contextual_precision: float = DEFAULT_CONTEXTUAL_PRECISION_THRESHOLD
    contextual_recall: float = DEFAULT_CONTEXTUAL_RECALL_THRESHOLD
    hallucination: float = DEFAULT_HALLUCINATION_THRESHOLD


def build_metrics(thresholds: EvalThresholds | None = None):
    """
    Build the 5 DeepEval metrics using the provided thresholds.
    Falls back to defaults when thresholds is None.
    Returns a list of metric instances.
    """
    from app.services.eval.bedrock_judge import bedrock_judge

    t = thresholds or EvalThresholds()

    try:
        from deepeval.metrics import (
            FaithfulnessMetric,
            AnswerRelevancyMetric,
            ContextualPrecisionMetric,
            ContextualRecallMetric,
            HallucinationMetric,
        )

        return [
            FaithfulnessMetric(model=bedrock_judge, threshold=t.faithfulness),
            AnswerRelevancyMetric(model=bedrock_judge, threshold=t.answer_relevancy),
            ContextualPrecisionMetric(model=bedrock_judge, threshold=t.contextual_precision),
            ContextualRecallMetric(model=bedrock_judge, threshold=t.contextual_recall),
            HallucinationMetric(model=bedrock_judge, threshold=t.hallucination),
        ]
    except ImportError:
        return []

# Feature: documind-platform, CI golden dataset regression
"""
CI/CD Regression Evaluation Suite

Loads golden Q&A datasets for financial, legal, and HR document categories
and asserts each case passes FaithfulnessMetric (≥0.85) and
AnswerRelevancyMetric (≥0.80) using the bedrock_judge model.

Validates: Requirements 14.1, 14.2, 14.3
"""
import json
import os
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"


def load_golden_dataset(category: str) -> list[dict]:
    """Load a JSONL golden dataset file and return list of test case dicts."""
    path = GOLDEN_DIR / f"{category}.jsonl"
    if not path.exists():
        return []
    cases = []
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as e:
                pytest.fail(f"Invalid JSON in {category}.jsonl line {line_num}: {e}")
    return cases


def _all_golden_cases() -> list[tuple[str, dict]]:
    """Return all golden cases as (category, case) tuples."""
    cases = []
    for category in ("financial", "legal", "hr"):
        for case in load_golden_dataset(category):
            cases.append((category, case))
    return cases


# ── Dataset integrity tests (run without Bedrock) ────────────────────────────

class TestGoldenDatasetIntegrity:
    """Validate the structure and completeness of golden datasets."""

    @pytest.mark.parametrize("category", ["financial", "legal", "hr"])
    def test_dataset_has_minimum_50_cases(self, category: str):
        """Each golden dataset must contain at least 50 Q&A pairs."""
        cases = load_golden_dataset(category)
        assert len(cases) >= 50, (
            f"{category}.jsonl has only {len(cases)} cases; minimum is 50"
        )

    @pytest.mark.parametrize("category", ["financial", "legal", "hr"])
    def test_all_cases_have_required_fields(self, category: str):
        """Every case must have input, actual_output, and retrieval_context."""
        cases = load_golden_dataset(category)
        required_fields = {"input", "actual_output", "retrieval_context"}
        for i, case in enumerate(cases):
            missing = required_fields - set(case.keys())
            assert not missing, (
                f"{category}.jsonl case {i + 1} missing fields: {missing}"
            )

    @pytest.mark.parametrize("category", ["financial", "legal", "hr"])
    def test_all_cases_have_non_empty_fields(self, category: str):
        """Every case must have non-empty values for all required fields."""
        cases = load_golden_dataset(category)
        for i, case in enumerate(cases):
            assert case.get("input", "").strip(), (
                f"{category}.jsonl case {i + 1}: 'input' is empty"
            )
            assert case.get("actual_output", "").strip(), (
                f"{category}.jsonl case {i + 1}: 'actual_output' is empty"
            )
            retrieval = case.get("retrieval_context", [])
            assert isinstance(retrieval, list) and len(retrieval) > 0, (
                f"{category}.jsonl case {i + 1}: 'retrieval_context' must be a non-empty list"
            )
            assert all(isinstance(c, str) and c.strip() for c in retrieval), (
                f"{category}.jsonl case {i + 1}: all retrieval_context items must be non-empty strings"
            )

    @pytest.mark.parametrize("category", ["financial", "legal", "hr"])
    def test_dataset_file_exists(self, category: str):
        """Golden dataset files must exist."""
        path = GOLDEN_DIR / f"{category}.jsonl"
        assert path.exists(), f"Golden dataset not found: {path}"


# ── DeepEval regression tests (require AWS Bedrock) ──────────────────────────

@pytest.mark.skipif(
    os.environ.get("SKIP_DEEPEVAL_TESTS", "true").lower() == "true",
    reason="DeepEval tests require AWS Bedrock access. Set SKIP_DEEPEVAL_TESTS=false to run.",
)
class TestRAGQuality:
    """
    CI/CD regression suite using DeepEval metrics against golden datasets.

    These tests require AWS Bedrock access and are skipped by default.
    Set SKIP_DEEPEVAL_TESTS=false in the environment to enable them.
    """

    @pytest.fixture(scope="class")
    def bedrock_judge(self):
        """Singleton bedrock judge model for evaluation."""
        from app.services.eval.bedrock_judge import bedrock_judge as judge
        return judge

    @pytest.fixture(scope="class")
    def faithfulness_metric(self, bedrock_judge):
        """FaithfulnessMetric with threshold ≥ 0.85."""
        from deepeval.metrics import FaithfulnessMetric
        return FaithfulnessMetric(model=bedrock_judge, threshold=0.85)

    @pytest.fixture(scope="class")
    def relevancy_metric(self, bedrock_judge):
        """AnswerRelevancyMetric with threshold ≥ 0.80."""
        from deepeval.metrics import AnswerRelevancyMetric
        return AnswerRelevancyMetric(model=bedrock_judge, threshold=0.80)

    def _run_case(self, case: dict, faithfulness_metric, relevancy_metric, category: str):
        """Run a single golden dataset case through DeepEval metrics."""
        from deepeval import assert_test
        from deepeval.test_case import LLMTestCase

        test_case = LLMTestCase(
            input=case["input"],
            actual_output=case["actual_output"],
            retrieval_context=case["retrieval_context"],
        )

        try:
            assert_test(test_case, [faithfulness_metric, relevancy_metric])
        except AssertionError as e:
            # Report specific metric, score, and reason on failure
            failure_details = []
            if not faithfulness_metric.is_successful():
                failure_details.append(
                    f"FaithfulnessMetric FAILED: score={faithfulness_metric.score:.3f} "
                    f"(threshold=0.85), reason={faithfulness_metric.reason}"
                )
            if not relevancy_metric.is_successful():
                failure_details.append(
                    f"AnswerRelevancyMetric FAILED: score={relevancy_metric.score:.3f} "
                    f"(threshold=0.80), reason={relevancy_metric.reason}"
                )
            pytest.fail(
                f"[{category}] Q: {case['input']!r}\n"
                + "\n".join(failure_details)
            )

    @pytest.mark.parametrize(
        "case",
        load_golden_dataset("financial"),
        ids=[f"financial_{i}" for i in range(len(load_golden_dataset("financial")))],
    )
    def test_financial_rag_quality(self, case, faithfulness_metric, relevancy_metric):
        """Financial golden dataset: each case must pass faithfulness and relevancy."""
        self._run_case(case, faithfulness_metric, relevancy_metric, "financial")

    @pytest.mark.parametrize(
        "case",
        load_golden_dataset("legal"),
        ids=[f"legal_{i}" for i in range(len(load_golden_dataset("legal")))],
    )
    def test_legal_rag_quality(self, case, faithfulness_metric, relevancy_metric):
        """Legal golden dataset: each case must pass faithfulness and relevancy."""
        self._run_case(case, faithfulness_metric, relevancy_metric, "legal")

    @pytest.mark.parametrize(
        "case",
        load_golden_dataset("hr"),
        ids=[f"hr_{i}" for i in range(len(load_golden_dataset("hr")))],
    )
    def test_hr_rag_quality(self, case, faithfulness_metric, relevancy_metric):
        """HR golden dataset: each case must pass faithfulness and relevancy."""
        self._run_case(case, faithfulness_metric, relevancy_metric, "hr")

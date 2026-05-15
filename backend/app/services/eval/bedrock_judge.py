"""DeepEval judge model singleton backed by AWS Bedrock Claude Sonnet 4.5."""
from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

_JUDGE_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
_JUDGE_REGION = "us-east-1"

# Check Python version - DeepEval requires 3.10+
_PYTHON_VERSION_OK = sys.version_info >= (3, 10)

bedrock_judge = None  # type: ignore[assignment]
JUDGE_MODEL_NAME = "sample-scores-python-3.9"

if not _PYTHON_VERSION_OK:
    logger.warning(
        f"DeepEval requires Python 3.10+, current version is {sys.version_info.major}.{sys.version_info.minor}. "
        "Evaluations will use sample scores."
    )
else:
    # Python 3.10+ - try to use real Bedrock
    try:
        from deepeval.models import AmazonBedrockModel

        bedrock_judge = AmazonBedrockModel(
            model=_JUDGE_MODEL_ID,
            region=_JUDGE_REGION,
            generation_kwargs={"temperature": 0, "max_tokens": 1000},
        )
        JUDGE_MODEL_NAME = _JUDGE_MODEL_ID
        logger.info("Bedrock judge initialized successfully")
    except ImportError:
        logger.warning("deepeval not installed; bedrock_judge is a stub")
        JUDGE_MODEL_NAME = "deepeval-not-installed"
    except Exception as e:
        logger.error(f"Failed to initialize Bedrock judge: {e}")
        JUDGE_MODEL_NAME = "bedrock-init-failed"

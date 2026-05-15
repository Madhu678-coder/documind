# Feature: documind-platform, Property 22: Structured Logs Contain Correlation ID
import json
import logging
import pytest
import anyio
from hypothesis import given, settings, strategies as st
from httpx import AsyncClient, ASGITransport
from app.main import app


# Strategy: generate simple ASCII path segments and HTTP methods
path_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=20,
).map(lambda s: "/" + s)

method_strategy = st.sampled_from(["GET", "POST"])


@given(path_strategy, method_strategy)
@settings(max_examples=50)
def test_access_log_contains_correlation_id(path: str, method: str):
    """Every access log entry must be valid JSON and contain a correlation_id."""

    async def run():
        log_records: list[str] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord):
                log_records.append(record.getMessage())

        # The access logger in main.py is "app.access"
        access_logger = logging.getLogger("app.access")
        # Ensure the logger is enabled and will propagate to our handler
        original_level = access_logger.level
        access_logger.setLevel(logging.DEBUG)
        handler = CapturingHandler()
        handler.setLevel(logging.DEBUG)
        access_logger.addHandler(handler)
        # Prevent propagation to root logger (which may have no handlers in test)
        original_propagate = access_logger.propagate
        access_logger.propagate = False

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                request_method = getattr(client, method.lower(), client.get)
                response = await request_method(path)
                response_cid = response.headers.get("X-Correlation-ID", "")
        finally:
            access_logger.removeHandler(handler)
            access_logger.setLevel(original_level)
            access_logger.propagate = original_propagate

        # At least one log record should have been emitted for this request
        assert len(log_records) >= 1, "No access log records captured"

        # The last record corresponds to this request
        last_record = log_records[-1]

        # Must be valid JSON
        try:
            entry = json.loads(last_record)
        except json.JSONDecodeError:
            pytest.fail(f"Log entry is not valid JSON: {last_record!r}")

        # Must contain correlation_id
        assert "correlation_id" in entry, f"Missing correlation_id in log entry: {entry}"

        # correlation_id must be non-empty
        assert entry["correlation_id"], "correlation_id is empty in log entry"

        # correlation_id in log must match the response header
        if response_cid:
            assert entry["correlation_id"] == response_cid, (
                f"Log correlation_id {entry['correlation_id']!r} "
                f"does not match response header {response_cid!r}"
            )

    anyio.run(run)

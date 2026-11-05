import json
from datetime import datetime, timezone

import pytest

from fde_incident_response.clock import DeterministicClock
from fde_incident_response.logging import (MemorySink, StructuredLogger,
                                           parse_log_line, query_logs,
                                           validate_record)


def make_logger():
    clock = DeterministicClock()
    sink = MemorySink()
    return StructuredLogger("api", sink, clock, tenant="acme"), sink, clock


def test_schema_keys_and_values():
    logger, sink, _ = make_logger()
    logger.info("hello", fields={"k": 1})
    record = parse_log_line(sink.lines[0])
    assert list(record.keys()) == ["ts", "level", "service", "tenant",
                                   "trace_id", "span_id", "msg", "fields"]
    assert record["ts"] == "2026-01-01T00:00:00Z"
    assert record["level"] == "INFO"
    assert record["service"] == "api"
    assert record["tenant"] == "acme"
    assert record["msg"] == "hello"
    assert record["fields"] == {"k": 1}
    # line is valid JSON on one line
    assert json.loads(sink.lines[0]) == record


def test_invalid_level_rejected():
    logger, _, _ = make_logger()
    with pytest.raises(ValueError):
        logger.log("LOUD", "nope")
    with pytest.raises(ValueError):
        validate_record({"ts": "2026-01-01T00:00:00Z", "level": "INFO", "service": "s",
                         "tenant": "t", "trace_id": "", "span_id": "", "msg": "m"})


def test_query_filters():
    logger, sink, clock = make_logger()
    logger.info("a", trace_id="trace-0001")
    clock.advance(minutes=10)
    logger.error("b", trace_id="trace-0001", tenant="other")
    clock.advance(minutes=10)
    logger.error("c", trace_id="trace-0002")
    records = sink.records()
    assert [r["msg"] for r in query_logs(records, trace_id="trace-0001")] == ["a", "b"]
    assert [r["msg"] for r in query_logs(records, tenant="other")] == ["b"]
    assert [r["msg"] for r in query_logs(records, level="ERROR")] == ["b", "c"]
    start = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc)
    assert [r["msg"] for r in query_logs(records, start=start, end=end)] == ["b"]
    # window boundaries are inclusive
    exact = datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)
    assert [r["msg"] for r in query_logs(records, start=exact, end=exact)] == ["b"]

"""Structured logging: JSON lines with a pinned schema.

Schema (every line, exactly these top-level keys):
  ts, level, service, tenant, trace_id, span_id, msg, fields
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable, Optional

from .clock import DeterministicClock
from .tracing import get_current_context

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
SCHEMA_KEYS = ("ts", "level", "service", "tenant", "trace_id", "span_id", "msg", "fields")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def validate_record(record: dict) -> dict:
    if tuple(record.keys()) != SCHEMA_KEYS and set(record.keys()) != set(SCHEMA_KEYS):
        raise ValueError(f"log record keys must be exactly {SCHEMA_KEYS}, got {sorted(record.keys())}")
    if record["level"] not in LEVELS:
        raise ValueError(f"invalid level {record['level']!r}")
    if not isinstance(record["fields"], dict):
        raise ValueError("fields must be a dict")
    _parse_ts(record["ts"])  # raises on a malformed timestamp
    return record


class MemorySink:
    def __init__(self):
        self.lines: list[str] = []

    def write(self, line: str) -> None:
        self.lines.append(line)

    def records(self) -> list[dict]:
        return [parse_log_line(line) for line in self.lines]


class FileSink:
    def __init__(self, path: str):
        self.path = path

    def write(self, line: str) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class StructuredLogger:
    def __init__(self, service: str, sink, clock: DeterministicClock, tenant: str = "default"):
        self.service = service
        self.sink = sink
        self.clock = clock
        self.tenant = tenant

    def log(self, level: str, msg: str, tenant: str | None = None,
            trace_id: str | None = None, span_id: str | None = None,
            fields: dict | None = None) -> dict:
        ctx = get_current_context()
        record = {
            "ts": _iso(self.clock.now()),
            "level": level,
            "service": self.service,
            "tenant": tenant if tenant is not None else self.tenant,
            "trace_id": trace_id if trace_id is not None else (ctx.trace_id if ctx else ""),
            "span_id": span_id if span_id is not None else (ctx.span_id if ctx else ""),
            "msg": msg,
            "fields": fields or {},
        }
        validate_record(record)
        self.sink.write(json.dumps(record, sort_keys=False))
        return record

    def debug(self, msg, **kw): return self.log("DEBUG", msg, **kw)
    def info(self, msg, **kw): return self.log("INFO", msg, **kw)
    def warning(self, msg, **kw): return self.log("WARNING", msg, **kw)
    def error(self, msg, **kw): return self.log("ERROR", msg, **kw)
    def critical(self, msg, **kw): return self.log("CRITICAL", msg, **kw)


def parse_log_line(line: str) -> dict:
    return validate_record(json.loads(line))


def query_logs(records: Iterable[dict], trace_id: str | None = None,
               tenant: str | None = None, level: str | None = None,
               start: datetime | None = None, end: datetime | None = None) -> list[dict]:
    """Filter parsed records. Time window is inclusive on both ends."""
    out = []
    for r in records:
        if trace_id is not None and r["trace_id"] != trace_id:
            continue
        if tenant is not None and r["tenant"] != tenant:
            continue
        if level is not None and r["level"] != level:
            continue
        if start is not None or end is not None:
            ts = _parse_ts(r["ts"])
            if start is not None and ts < start:
                continue
            if end is not None and ts > end:
                continue
        out.append(r)
    return out

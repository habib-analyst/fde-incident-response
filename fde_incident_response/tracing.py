"""Distributed-tracing primitives: context propagation, spans, span trees.

Propagation uses contextvars, so a context set by a caller is visible to
in-process callees (the demo's api -> worker -> db pipeline) without
threading arguments through every signature.

Orphan handling: a span whose parent_span_id points at a span that is not
present in the span set is NOT dropped. It becomes a root of the rebuilt
tree and is flagged ``orphan=True`` on its tree node. A span with
parent_span_id=None is a normal root (orphan=False).
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterator, Optional

from .clock import DeterministicClock, SequentialIds

_current: contextvars.ContextVar[Optional["TraceContext"]] = contextvars.ContextVar(
    "fde_trace_context", default=None
)


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None


def get_current_context() -> Optional[TraceContext]:
    return _current.get()


def set_current_context(ctx: Optional[TraceContext]):
    return _current.set(ctx)


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    name: str
    service: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "ok"
    attributes: dict = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time).total_seconds()


@dataclass
class SpanNode:
    span: Span
    children: list["SpanNode"] = field(default_factory=list)
    orphan: bool = False


class Tracer:
    def __init__(self, clock: DeterministicClock | Callable[[], datetime], ids: SequentialIds | None = None):
        self._clock = clock
        self._ids = ids or SequentialIds()
        self.spans: list[Span] = []

    def _now(self) -> datetime:
        return self._clock() if callable(self._clock) else self._clock.now()  # type: ignore

    # DeterministicClock is callable, plain callables work too.
    def now(self) -> datetime:
        try:
            return self._clock.now()  # type: ignore[attr-defined]
        except AttributeError:
            return self._clock()  # type: ignore

    @contextmanager
    def start_span(self, name: str, service: str, trace_id: str | None = None) -> Iterator[Span]:
        parent = get_current_context()
        if trace_id is not None:
            tid = trace_id
        elif parent is not None:
            tid = parent.trace_id
        else:
            tid = self._ids.next("trace")
        span_id = self._ids.next("span")
        span = Span(
            trace_id=tid,
            span_id=span_id,
            parent_span_id=parent.span_id if parent else None,
            name=name,
            service=service,
            start_time=self.now(),
        )
        token = _current.set(TraceContext(trace_id=tid, span_id=span_id,
                                          parent_span_id=span.parent_span_id))
        try:
            yield span
        finally:
            span.end_time = self.now()
            self.spans.append(span)
            _current.reset(token)

    def spans_for_trace(self, trace_id: str) -> list[Span]:
        return [s for s in self.spans if s.trace_id == trace_id]


def build_span_tree(spans: list[Span]) -> list[SpanNode]:
    """Rebuild the span tree. Roots in start-time order; children likewise.

    Missing-parent (orphan) spans become roots flagged orphan=True.
    """
    by_id = {s.span_id: SpanNode(span=s) for s in spans}
    roots: list[SpanNode] = []
    for span in sorted(spans, key=lambda s: (s.start_time, s.span_id)):
        node = by_id[span.span_id]
        if span.parent_span_id is None:
            roots.append(node)
        elif span.parent_span_id in by_id:
            by_id[span.parent_span_id].children.append(node)
        else:
            node.orphan = True
            roots.append(node)
    for node in by_id.values():
        node.children.sort(key=lambda n: (n.span.start_time, n.span.span_id))
    roots.sort(key=lambda n: (n.span.start_time, n.span.span_id))
    return roots


def flatten_tree(nodes: list[SpanNode]) -> list[Span]:
    """Pre-order traversal: parent before its children, in tree order."""
    out: list[Span] = []
    for node in nodes:
        out.append(node.span)
        out.extend(flatten_tree(node.children))
    return out


def trace_view(spans: list[Span], trace_id: str) -> dict:
    """Reconstruct one request's path across services."""
    selected = [s for s in spans if s.trace_id == trace_id]
    tree = build_span_tree(selected)
    ordered = flatten_tree(tree)
    return {
        "trace_id": trace_id,
        "span_count": len(ordered),
        "services": list(dict.fromkeys(s.service for s in ordered)),
        "spans": [
            {
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id,
                "name": s.name,
                "service": s.service,
                "duration_seconds": s.duration_seconds,
            }
            for s in ordered
        ],
        "tree": tree,
    }

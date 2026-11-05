from fde_incident_response.clock import DeterministicClock, SequentialIds
from fde_incident_response.demo import run_demo_pipeline
from fde_incident_response.tracing import (Span, Tracer, build_span_tree,
                                           flatten_tree, get_current_context,
                                           trace_view)
from datetime import datetime, timezone


def test_demo_pipeline_trace_shape_and_durations():
    _, tracer, sink, trace_id = run_demo_pipeline()
    view = trace_view(tracer.spans, trace_id)
    assert view["span_count"] == 3
    assert view["services"] == ["api", "worker", "db"]
    tree = build_span_tree(tracer.spans)
    assert len(tree) == 1
    root = tree[0]
    assert root.span.name == "api.handle_request" and not root.orphan
    assert len(root.children) == 1
    worker = root.children[0]
    assert worker.span.name == "worker.process"
    assert len(worker.children) == 1
    assert worker.children[0].span.name == "db.query"
    durations = {s.name: s.duration_seconds for s in flatten_tree(tree)}
    assert durations == {"api.handle_request": 8.0, "worker.process": 6.0, "db.query": 2.0}
    ordered = [s.name for s in flatten_tree(tree)]
    assert ordered == ["api.handle_request", "worker.process", "db.query"]
    assert len(sink.lines) == 5


def test_cross_service_propagation_via_contextvars():
    clock = DeterministicClock()
    tracer = Tracer(clock=clock, ids=SequentialIds())
    seen = {}
    with tracer.start_span("outer", service="api"):
        seen["outer"] = get_current_context()
        with tracer.start_span("inner", service="worker"):
            seen["inner"] = get_current_context()
    assert seen["inner"].trace_id == seen["outer"].trace_id
    assert seen["inner"].parent_span_id == seen["outer"].span_id
    assert get_current_context() is None  # restored after exit


def test_orphan_span_becomes_flagged_root():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    orphan = Span(trace_id="trace-0001", span_id="span-0009", parent_span_id="span-missing",
                  name="lost", service="worker", start_time=t0, end_time=t0)
    root = Span(trace_id="trace-0001", span_id="span-0001", parent_span_id=None,
                name="root", service="api", start_time=t0, end_time=t0)
    tree = build_span_tree([orphan, root])
    by_name = {n.span.name: n for n in tree}
    assert set(by_name) == {"lost", "root"}
    assert by_name["lost"].orphan is True
    assert by_name["root"].orphan is False

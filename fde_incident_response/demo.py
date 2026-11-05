"""Demo pipeline: 3 in-process services (api -> worker -> db shim).

One call produces one full trace across all three services, structured
logs correlated by trace_id, and (in main) a sample incident rendered
into a post-mortem.
"""
from __future__ import annotations

from .clock import DeterministicClock, SequentialIds
from .logging import MemorySink, StructuredLogger
from .tracing import Tracer, build_span_tree, flatten_tree, trace_view


def db_shim(tracer: Tracer, logger: StructuredLogger, clock: DeterministicClock) -> str:
    with tracer.start_span("db.query", service="db"):
        clock.advance(seconds=2)
        logger.info("query executed", fields={"rows": 1})
        return "row-1"


def worker_service(tracer: Tracer, logger: StructuredLogger, clock: DeterministicClock) -> str:
    with tracer.start_span("worker.process", service="worker"):
        clock.advance(seconds=3)
        logger.info("job picked up")
        result = db_shim(tracer, logger, clock)
        clock.advance(seconds=1)
        logger.info("job finished", fields={"result": result})
        return result


def api_service(tracer: Tracer, logger: StructuredLogger, clock: DeterministicClock) -> str:
    with tracer.start_span("api.handle_request", service="api"):
        clock.advance(seconds=1)
        logger.info("request received", fields={"path": "/jobs"})
        result = worker_service(tracer, logger, clock)
        clock.advance(seconds=1)
        logger.info("response sent", fields={"status": 200})
        return result


def run_demo_pipeline():
    """Run the pipeline once; return (clock, tracer, sink, trace_id)."""
    clock = DeterministicClock()
    ids = SequentialIds()
    tracer = Tracer(clock=clock, ids=ids)
    sink = MemorySink()
    logger = StructuredLogger(service="api", sink=sink, clock=clock, tenant="acme")
    # The logger's service label is per-logger; pipeline spans carry services.
    api_service(tracer, logger, clock)
    trace_id = tracer.spans[0].trace_id if tracer.spans else ""
    return clock, tracer, sink, trace_id


def main() -> None:
    from .incidents import IncidentStore
    from .postmortem import render_postmortem

    clock, tracer, sink, trace_id = run_demo_pipeline()
    view = trace_view(tracer.spans, trace_id)
    print(f"Trace {trace_id}: {view['span_count']} spans across {', '.join(view['services'])}")
    for span in flatten_tree(build_span_tree(tracer.spans)):
        print(f"  {span.service}/{span.name}: {span.duration_seconds:.0f}s")
    print(f"Log lines: {len(sink.lines)}")

    store = IncidentStore(clock=clock)
    inc = store.create_from_alert({
        "source": "demo", "key": "api-latency", "title": "API latency spike",
        "impact": "high", "urgency": "high", "service": "api", "tenant": "acme",
        "impact_description": "API latency above threshold for tenant acme.",
        "trace_id": trace_id,
    })
    clock.advance(minutes=5)
    store.transition(inc.id, "acknowledged", actor="oncall")
    store.add_note(inc.id, "ACTION: add latency alert threshold review @sam", actor="oncall")
    clock.advance(minutes=25)
    store.transition(inc.id, "mitigated", actor="oncall")
    clock.advance(minutes=30)
    store.transition(inc.id, "resolved", actor="oncall")
    store.transition(inc.id, "postmortem", actor="oncall")
    inc = store.get(inc.id)
    print()
    print(render_postmortem(inc, store.timeline(inc.id)))


if __name__ == "__main__":
    main()

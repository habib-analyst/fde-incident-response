# fde-incident-response

An incident response system for a SaaS operations team, in one local
Python package: structured logging, distributed-tracing primitives, an
incident manager, and post-mortem generation with a comms playbook
library. Everything runs locally with no network calls. Time and IDs are
injected (a deterministic clock and sequential ID generator), so every
run, test, and rendered document is reproducible byte for byte.

## The four parts

### 1. Structured logging

`StructuredLogger` emits one JSON object per line with a pinned schema —
exactly these keys, in this order:

`ts, level, service, tenant, trace_id, span_id, msg, fields`

Records are schema-validated before they are written and again when
parsed. Sinks are in-memory (`MemorySink`, for tests and embedding) or a
file (`FileSink`, JSON-lines). `query_logs` filters parsed records by
`trace_id`, `tenant`, `level`, and an inclusive time window. When a trace
context is active, the logger fills `trace_id` and `span_id` from it
automatically, so log lines correlate with spans without manual plumbing.

### 2. Tracing

A `Tracer` creates spans with parent links. The current context travels
through in-process calls via `contextvars`, the same propagation shape a
real tracer uses across service boundaries. `build_span_tree` rebuilds
the span tree for a trace (roots and children in start-time order) and
`trace_view` reconstructs one request's path across services with
per-span durations taken from the injected clock.

Orphan handling: a span whose parent ID is not present in the span set is
never dropped. It becomes a root of the rebuilt tree flagged
`orphan=True`, so a partial trace export still renders and the gap is
visible. This behavior is covered by a dedicated test.

The included demo pipeline runs three in-process services —
api → worker → db shim — and produces one full trace:

| Span | Service | Duration |
|------|---------|----------|
| api.handle_request | api | 8s |
| worker.process | worker | 6s |
| db.query | db | 2s |

### 3. Incident manager

Incidents live in SQLite (`IncidentStore`, file or in-memory). They are
declared from an alert payload or manually.

- **Dedupe:** an alert whose `source` + `key` matches an existing open
  incident updates that incident (occurrence count + 1, timeline entry)
  instead of creating a duplicate. Once the incident is resolved, a new
  alert with the same key opens a fresh incident.
- **Severity matrix:** `severity_from_matrix(impact, urgency)` maps
  high/medium/low impact × urgency to SEV1–SEV4 (for example
  high × high = SEV1, low × low = SEV4). All nine cells are tested.
- **Lifecycle:** `triggered → acknowledged → mitigated → resolved →
  postmortem`, enforced. An illegal transition raises
  `InvalidTransitionError` and changes nothing.
- **Timeline:** every creation, transition, alert re-fire, note, and
  trace attachment appends a timeline entry, in order. Trace IDs attach
  to the incident and appear in its post-mortem.

### 4. Post-mortems and comms playbooks

`render_postmortem` renders a complete Markdown post-mortem from the
incident record and the template in `templates/postmortem.md`: summary,
the full timeline in order, the impact section from the incident fields,
a root-cause section for the owner to complete, computed durations, and
an action-items table. Notes whose lines carry a `TODO:` or `ACTION:`
marker become action items; an `@name` or `[owner: name]` on the same
line sets the owner, and items without one are listed as Unassigned. A
golden test pins one rendered post-mortem byte for byte.

The playbook library in `templates/comms/` holds one status-page
template per stage × severity — investigating, identified, monitoring,
resolved × SEV1–SEV4, 16 templates — and `render_status_update` produces
the same updates programmatically. The cadence helper answers "is an
update due?" from severity and elapsed time:

| Severity | Update cadence |
|----------|---------------|
| SEV1 | every 30 minutes |
| SEV2 | every 60 minutes |
| SEV3 | every 4 hours |
| SEV4 | daily |

The boundary is inclusive: an update is due exactly at the cadence mark.
Every boundary is tested one second before, at, and after.

## Run the demo

```bash
python3 -m fde_incident_response.demo
```

This runs the api → worker → db pipeline, prints the trace tree and log
count, then declares a sample SEV1 incident, walks it through the full
lifecycle, and prints its rendered post-mortem.

## Tests

```bash
python3 -m pytest tests/ -q
```

42 tests, all passing. Coverage: log schema and every query filter,
trace tree shape, span durations, cross-service context propagation,
orphan spans, incident dedupe (open and post-resolve), all nine severity
matrix cells, legal and illegal lifecycle transitions, timeline
ordering, duration math, the byte-for-byte golden post-mortem,
action-item extraction with and without owners, and cadence boundaries
for all four severities.

## Measured results

- Test suite: **42 passed**.
- Demo trace: 3 spans across 3 services, durations 8s / 6s / 2s, 5
  correlated log lines, identical on every run.
- Sample incident (the golden post-mortem in `tests/golden_postmortem.md`,
  SEV1, declared from a pager alert): time to acknowledge **600s**, time
  to mitigate **1800s**, time to resolve **3600s**, 8 timeline entries,
  2 action items extracted with owners.

## Scope and honesty

- The three "services" are an in-process simulation: separate span and
  log contexts, one process, no sockets. The propagation model mirrors
  real distributed tracing, but nothing here talks to a network, a real
  alertmanager, or a real status page.
- Storage is a single local SQLite database. There is no multi-user
  concurrency story, no authentication, and no alert ingestion endpoint;
  alert payloads are plain dicts passed to `create_from_alert`.
- Root cause in a generated post-mortem is a placeholder section by
  design. The system assembles the facts; the incident owner writes the
  cause.
- Deterministic by construction: wall-clock time is never read. Pass
  your own clock and ID generator to run it against real time.

## Layout

```
fde_incident_response/
    clock.py       deterministic clock + sequential IDs
    logging.py     structured logger, sinks, parser, query helper
    tracing.py     spans, context propagation, span-tree builder, trace view
    incidents.py   SQLite incident store, dedupe, severity matrix, lifecycle
    postmortem.py  post-mortem renderer + action-item extraction
    comms.py       status-update rendering + cadence rules
    demo.py        api -> worker -> db demo pipeline + sample incident
templates/
    postmortem.md          post-mortem template
    comms/                 16 status-update templates (stage x severity)
tests/                     42 pytest tests + golden_postmortem.md
```

## License

MIT — see `LICENSE`.

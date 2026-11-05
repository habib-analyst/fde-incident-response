import pytest

from fde_incident_response.clock import DeterministicClock
from fde_incident_response.incidents import (IncidentStore,
                                             InvalidTransitionError,
                                             severity_from_matrix)

ALERT = {"source": "pager", "key": "db-down", "title": "DB down",
         "impact": "high", "urgency": "high", "service": "db", "tenant": "acme"}


def make_store():
    clock = DeterministicClock()
    return IncidentStore(clock=clock), clock


def test_dedupe_same_source_and_key():
    store, _ = make_store()
    first = store.create_from_alert(dict(ALERT))
    second = store.create_from_alert(dict(ALERT))
    assert second.id == first.id
    assert second.occurrences == 2
    assert store.count() == 1
    # a different key is a different incident
    third = store.create_from_alert({**ALERT, "key": "api-down"})
    assert third.id != first.id
    assert store.count() == 2


def test_dedupe_does_not_apply_after_resolve():
    store, _ = make_store()
    first = store.create_from_alert(dict(ALERT))
    for status in ("acknowledged", "mitigated", "resolved"):
        store.transition(first.id, status)
    again = store.create_from_alert(dict(ALERT))
    assert again.id != first.id
    assert store.count() == 2


@pytest.mark.parametrize("impact,urgency,expected", [
    ("high", "high", "SEV1"), ("high", "medium", "SEV1"), ("high", "low", "SEV2"),
    ("medium", "high", "SEV2"), ("medium", "medium", "SEV2"), ("medium", "low", "SEV3"),
    ("low", "high", "SEV3"), ("low", "medium", "SEV3"), ("low", "low", "SEV4"),
])
def test_severity_matrix_cells(impact, urgency, expected):
    assert severity_from_matrix(impact, urgency) == expected


def test_lifecycle_legal_path():
    store, _ = make_store()
    inc = store.create_from_alert(dict(ALERT))
    assert inc.status == "triggered" and inc.severity == "SEV1"
    for status in ("acknowledged", "mitigated", "resolved", "postmortem"):
        inc = store.transition(inc.id, status)
    assert inc.status == "postmortem"


@pytest.mark.parametrize("frm,to", [
    ("triggered", "mitigated"), ("triggered", "resolved"), ("triggered", "postmortem"),
    ("acknowledged", "resolved"), ("acknowledged", "triggered"),
    ("resolved", "acknowledged"), ("postmortem", "resolved"),
])
def test_lifecycle_illegal_transitions(frm, to):
    store, _ = make_store()
    inc = store.create_from_alert(dict(ALERT))
    path = ["acknowledged", "mitigated", "resolved", "postmortem"]
    for status in path:
        if inc.status == frm:
            break
        inc = store.transition(inc.id, status)
    assert inc.status == frm
    with pytest.raises(InvalidTransitionError):
        store.transition(inc.id, to)


def test_timeline_ordering_and_auto_entries():
    store, clock = make_store()
    inc = store.create_from_alert(dict(ALERT))
    clock.advance(minutes=1)
    store.transition(inc.id, "acknowledged", actor="oncall")
    clock.advance(minutes=1)
    store.add_note(inc.id, "looking into it", actor="oncall")
    store.attach_trace(inc.id, "trace-0001")
    entries = store.timeline(inc.id)
    assert [e.kind for e in entries] == ["created", "transition", "note", "trace"]
    assert [e.ts for e in entries] == sorted(e.ts for e in entries)
    assert entries[1].message == "Status changed triggered -> acknowledged"
    assert store.get(inc.id).trace_ids == ["trace-0001"]

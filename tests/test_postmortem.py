from pathlib import Path

from fde_incident_response.clock import DeterministicClock
from fde_incident_response.incidents import IncidentStore
from fde_incident_response.postmortem import extract_action_items, render_postmortem

GOLDEN = Path(__file__).parent / "golden_postmortem.md"


def build_incident():
    clock = DeterministicClock()
    store = IncidentStore(clock=clock)
    inc = store.create_from_alert({
        "source": "pager", "key": "checkout-down", "title": "Checkout down",
        "impact": "high", "urgency": "high", "service": "checkout", "tenant": "acme",
        "impact_description": "Checkout unavailable for all customers.",
        "trace_id": "trace-0001",
    }, actor="alertmanager")
    clock.advance(minutes=10)
    store.transition(inc.id, "acknowledged", actor="oncall")
    store.add_note(inc.id, "Investigating database saturation.", actor="oncall")
    store.add_note(inc.id, "TODO: add connection pool alert @priya", actor="oncall")
    clock.advance(minutes=20)
    store.transition(inc.id, "mitigated", actor="oncall")
    store.add_note(inc.id, "ACTION: raise pool limit [owner: sam]", actor="oncall")
    clock.advance(minutes=30)
    store.transition(inc.id, "resolved", actor="oncall")
    store.transition(inc.id, "postmortem", actor="oncall")
    return store, store.get(inc.id)


def test_golden_render_byte_for_byte():
    store, inc = build_incident()
    rendered = render_postmortem(inc, store.timeline(inc.id))
    assert rendered == GOLDEN.read_text(encoding="utf-8")


def test_duration_math_and_sections():
    store, inc = build_incident()
    rendered = render_postmortem(inc, store.timeline(inc.id))
    assert "- Time to acknowledge: 600s" in rendered
    assert "- Time to mitigate: 1800s" in rendered
    assert "- Time to resolve: 3600s" in rendered
    assert "Checkout unavailable for all customers." in rendered
    assert "trace-0001" in rendered
    # full timeline, in order
    created = rendered.index("Incident declared from alert")
    ack = rendered.index("Status changed triggered -> acknowledged")
    resolved = rendered.index("Status changed mitigated -> resolved")
    assert created < ack < resolved


def test_action_item_extraction():
    store, inc = build_incident()
    items = extract_action_items(store.timeline(inc.id))
    assert items == [
        {"item": "add connection pool alert", "owner": "priya"},
        {"item": "raise pool limit", "owner": "sam"},
    ]
    store2_inc = store.get(inc.id)
    rendered = render_postmortem(store2_inc, store.timeline(inc.id))
    assert "| 1 | add connection pool alert | priya |" in rendered
    assert "| 2 | raise pool limit | sam |" in rendered


def test_action_item_without_owner_is_unassigned():
    clock = DeterministicClock()
    store = IncidentStore(clock=clock)
    inc = store.create_manual("Small outage", severity="SEV4")
    store.add_note(inc.id, "TODO: write the runbook")
    items = extract_action_items(store.timeline(inc.id))
    assert items == [{"item": "write the runbook", "owner": "Unassigned"}]

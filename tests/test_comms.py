from datetime import timedelta

import pytest

from fde_incident_response.comms import (CADENCE, STAGES, cadence_for,
                                         is_update_due, next_update_in,
                                         render_status_update)

CASES = [("SEV1", timedelta(minutes=30)), ("SEV2", timedelta(minutes=60)),
         ("SEV3", timedelta(hours=4)), ("SEV4", timedelta(days=1))]


@pytest.mark.parametrize("severity,cadence", CASES)
def test_cadence_values(severity, cadence):
    assert cadence_for(severity) == cadence
    assert CADENCE[severity] == cadence


@pytest.mark.parametrize("severity,cadence", CASES)
def test_cadence_boundaries(severity, cadence):
    assert is_update_due(severity, cadence - timedelta(seconds=1)) is False
    assert is_update_due(severity, cadence) is True  # boundary is inclusive
    assert is_update_due(severity, cadence + timedelta(seconds=1)) is True
    assert is_update_due(severity, timedelta(0)) is False
    assert next_update_in(severity, timedelta(0)) == cadence
    assert next_update_in(severity, cadence) == timedelta(0)


def test_status_update_templates_all_combinations():
    for severity, _ in CASES:
        for stage in STAGES:
            text = render_status_update(severity, stage, "Checkout down", detail="Detail line.")
            assert text.startswith(f"[{severity}] Checkout down — {stage}")
            assert "Detail line." in text
    with pytest.raises(ValueError):
        render_status_update("SEV9", "investigating", "x")
    with pytest.raises(ValueError):
        render_status_update("SEV1", "unknown-stage", "x")

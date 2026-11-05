"""Comms playbooks: status-update templates and cadence rules."""
from __future__ import annotations

from datetime import timedelta

STAGES = ("investigating", "identified", "monitoring", "resolved")
SEVERITIES = ("SEV1", "SEV2", "SEV3", "SEV4")

CADENCE: dict[str, timedelta] = {
    "SEV1": timedelta(minutes=30),
    "SEV2": timedelta(minutes=60),
    "SEV3": timedelta(hours=4),
    "SEV4": timedelta(days=1),
}

_STAGE_LEAD = {
    "investigating": "We are investigating reports of an issue.",
    "identified": "We have identified the cause and are working on a fix.",
    "monitoring": "A fix has been applied and we are monitoring the results.",
    "resolved": "This incident has been resolved.",
}

_SEVERITY_SCOPE = {
    "SEV1": "All customers are affected.",
    "SEV2": "Many customers are affected.",
    "SEV3": "Some customers are affected.",
    "SEV4": "Impact is limited to a small number of customers.",
}


def cadence_for(severity: str) -> timedelta:
    if severity not in CADENCE:
        raise ValueError(f"unknown severity {severity!r}")
    return CADENCE[severity]


def is_update_due(severity: str, elapsed: timedelta) -> bool:
    """An update is due when elapsed >= the severity's cadence (boundary inclusive)."""
    return elapsed >= cadence_for(severity)


def next_update_in(severity: str, elapsed: timedelta) -> timedelta:
    remaining = cadence_for(severity) - elapsed
    return remaining if remaining > timedelta(0) else timedelta(0)


def render_status_update(severity: str, stage: str, title: str, detail: str = "") -> str:
    if severity not in SEVERITIES:
        raise ValueError(f"unknown severity {severity!r}")
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    lines = [
        f"[{severity}] {title} — {stage}",
        "",
        _STAGE_LEAD[stage],
        _SEVERITY_SCOPE[severity],
    ]
    if detail:
        lines.append(detail)
    lines.append(f"Next update within {int(cadence_for(severity).total_seconds() // 60)} minutes."
                 if severity in ("SEV1", "SEV2", "SEV3") else "Next update within 24 hours.")
    return "\n".join(lines)

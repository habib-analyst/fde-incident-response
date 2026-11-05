"""Post-mortem generation from an incident record.

Duration math is computed from the incident's stored timestamps, which
come from the injected clock, so renders are fully deterministic.
Action items are extracted from timeline notes: any line containing a
``TODO:`` or ``ACTION:`` marker becomes an action item; an ``@name`` or
``[owner: name]`` in the same line sets the owner.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .incidents import Incident, TimelineEntry

DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "postmortem.md"

_ACTION_RE = re.compile(r"(?:TODO|ACTION)\s*[:\-]\s*(.+)$")
_OWNER_AT_RE = re.compile(r"@([A-Za-z0-9_.-]+)")
_OWNER_BRACKET_RE = re.compile(r"\[owner:\s*([^\]]+)\]")


def _fmt_ts(dt: datetime | None) -> str:
    if dt is None:
        return "n/a"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _duration(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return "n/a"
    total = int((end - start).total_seconds())
    return f"{total}s"


def extract_action_items(entries: list[TimelineEntry]) -> list[dict]:
    items: list[dict] = []
    for entry in entries:
        for line in entry.message.splitlines():
            m = _ACTION_RE.search(line)
            if not m:
                continue
            text = m.group(1).strip()
            owner = ""
            bracket = _OWNER_BRACKET_RE.search(text)
            at = _OWNER_AT_RE.search(text)
            if bracket:
                owner = bracket.group(1).strip()
                text = _OWNER_BRACKET_RE.sub("", text).strip()
            elif at:
                owner = at.group(1).strip()
                text = _OWNER_AT_RE.sub("", text).strip()
            items.append({"item": text.rstrip(), "owner": owner or "Unassigned"})
    return items


def render_postmortem(incident: Incident, entries: list[TimelineEntry],
                      template_path: str | Path | None = None) -> str:
    path = Path(template_path) if template_path else DEFAULT_TEMPLATE_PATH
    template = path.read_text(encoding="utf-8")

    timeline_lines = [
        f"- {_fmt_ts(e.ts)} [{e.kind}] {e.message}" + (f" ({e.actor})" if e.actor else "")
        for e in entries
    ]
    actions = extract_action_items(entries)
    if actions:
        action_lines = ["| # | Action Item | Owner |", "|---|-------------|-------|"]
        action_lines += [f"| {i} | {a['item']} | {a['owner']} |" for i, a in enumerate(actions, 1)]
        action_block = "\n".join(action_lines)
    else:
        action_block = "No action items."

    values = {
        "id": incident.id,
        "title": incident.title,
        "severity": incident.severity,
        "status": incident.status,
        "service": incident.service or "n/a",
        "tenant": incident.tenant,
        "created_at": _fmt_ts(incident.created_at),
        "time_to_acknowledge": _duration(incident.created_at, incident.acknowledged_at),
        "time_to_mitigate": _duration(incident.created_at, incident.mitigated_at),
        "time_to_resolve": _duration(incident.created_at, incident.resolved_at),
        "impact_description": incident.impact_description or "No impact description recorded.",
        "trace_ids": ", ".join(incident.trace_ids) if incident.trace_ids else "None attached.",
        "timeline": "\n".join(timeline_lines) if timeline_lines else "No timeline entries.",
        "action_items": action_block,
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered

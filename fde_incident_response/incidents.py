"""Incident manager: SQLite storage, dedupe, severity matrix, lifecycle."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .clock import DeterministicClock, SequentialIds

SEVERITIES = ("SEV1", "SEV2", "SEV3", "SEV4")
STATUSES = ("triggered", "acknowledged", "mitigated", "resolved", "postmortem")
OPEN_STATUSES = ("triggered", "acknowledged", "mitigated")

# Legal lifecycle transitions. Anything else raises InvalidTransitionError.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "triggered": ("acknowledged",),
    "acknowledged": ("mitigated",),
    "mitigated": ("resolved",),
    "resolved": ("postmortem",),
    "postmortem": (),
}

# impact x urgency -> severity
_MATRIX = {
    ("high", "high"): "SEV1", ("high", "medium"): "SEV1", ("high", "low"): "SEV2",
    ("medium", "high"): "SEV2", ("medium", "medium"): "SEV2", ("medium", "low"): "SEV3",
    ("low", "high"): "SEV3", ("low", "medium"): "SEV3", ("low", "low"): "SEV4",
}


def severity_from_matrix(impact: str, urgency: str) -> str:
    key = (impact.lower(), urgency.lower())
    if key not in _MATRIX:
        raise ValueError(f"impact/urgency must be high|medium|low, got {impact!r}/{urgency!r}")
    return _MATRIX[key]


class InvalidTransitionError(ValueError):
    pass


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


@dataclass
class TimelineEntry:
    id: int | None
    incident_id: str
    ts: datetime
    kind: str  # created | transition | note | alert | trace
    message: str
    actor: str = ""


@dataclass
class Incident:
    id: str
    title: str
    severity: str
    status: str
    source: str
    alert_key: str
    tenant: str = "default"
    service: str = ""
    impact_description: str = ""
    impact: str = "medium"
    urgency: str = "medium"
    created_at: datetime | None = None
    acknowledged_at: datetime | None = None
    mitigated_at: datetime | None = None
    resolved_at: datetime | None = None
    postmortem_at: datetime | None = None
    occurrences: int = 1
    trace_ids: list[str] = field(default_factory=list)


class IncidentStore:
    def __init__(self, db_path: str = ":memory:", clock: DeterministicClock | None = None,
                 ids: SequentialIds | None = None):
        self.clock = clock or DeterministicClock()
        self.ids = ids or SequentialIds()
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY, title TEXT, severity TEXT, status TEXT,
                source TEXT, alert_key TEXT, tenant TEXT, service TEXT,
                impact_description TEXT, impact TEXT, urgency TEXT,
                created_at TEXT, acknowledged_at TEXT, mitigated_at TEXT,
                resolved_at TEXT, postmortem_at TEXT,
                occurrences INTEGER, trace_ids TEXT
            );
            CREATE TABLE IF NOT EXISTS timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT,
                ts TEXT, kind TEXT, message TEXT, actor TEXT
            );
        """)
        self.conn.commit()

    # -- internal helpers -------------------------------------------------
    def _save(self, inc: Incident) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (inc.id, inc.title, inc.severity, inc.status, inc.source, inc.alert_key,
             inc.tenant, inc.service, inc.impact_description, inc.impact, inc.urgency,
             _iso(inc.created_at), _iso(inc.acknowledged_at), _iso(inc.mitigated_at),
             _iso(inc.resolved_at), _iso(inc.postmortem_at), inc.occurrences,
             json.dumps(inc.trace_ids)))
        self.conn.commit()

    def _row_to_incident(self, row) -> Incident:
        return Incident(
            id=row["id"], title=row["title"], severity=row["severity"], status=row["status"],
            source=row["source"], alert_key=row["alert_key"], tenant=row["tenant"],
            service=row["service"], impact_description=row["impact_description"],
            impact=row["impact"], urgency=row["urgency"],
            created_at=_parse(row["created_at"]), acknowledged_at=_parse(row["acknowledged_at"]),
            mitigated_at=_parse(row["mitigated_at"]), resolved_at=_parse(row["resolved_at"]),
            postmortem_at=_parse(row["postmortem_at"]), occurrences=row["occurrences"],
            trace_ids=json.loads(row["trace_ids"] or "[]"))

    def _timeline(self, incident_id: str, kind: str, message: str, actor: str = "") -> None:
        self.conn.execute(
            "INSERT INTO timeline (incident_id, ts, kind, message, actor) VALUES (?,?,?,?,?)",
            (incident_id, _iso(self.clock.now()), kind, message, actor))
        self.conn.commit()

    # -- API ---------------------------------------------------------------
    def get(self, incident_id: str) -> Incident:
        row = self.conn.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            raise KeyError(incident_id)
        return self._row_to_incident(row)

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]

    def create_from_alert(self, payload: dict, actor: str = "alertmanager") -> Incident:
        """Create from an alert payload, deduping on (source, alert_key).

        An existing OPEN incident for the same source+key is updated
        (occurrences + 1, timeline entry) instead of duplicated.
        """
        source = payload["source"]
        key = payload["key"] if "key" in payload else payload["alert_key"]
        row = self.conn.execute(
            "SELECT * FROM incidents WHERE source=? AND alert_key=? AND status IN (?,?,?)",
            (source, key, *OPEN_STATUSES)).fetchone()
        if row is not None:
            inc = self._row_to_incident(row)
            inc.occurrences += 1
            if payload.get("title"):
                inc.title = payload["title"]
            self._save(inc)
            self._timeline(inc.id, "alert",
                           f"Alert re-fired from {source} (occurrence {inc.occurrences})", actor)
            return inc

        impact = payload.get("impact", "medium")
        urgency = payload.get("urgency", "medium")
        severity = payload.get("severity") or severity_from_matrix(impact, urgency)
        if severity not in SEVERITIES:
            raise ValueError(f"invalid severity {severity!r}")
        inc = Incident(
            id=self.ids.next("inc"),
            title=payload.get("title", f"Alert {key}"),
            severity=severity, status="triggered", source=source, alert_key=key,
            tenant=payload.get("tenant", "default"), service=payload.get("service", ""),
            impact_description=payload.get("impact_description", payload.get("description", "")),
            impact=impact, urgency=urgency, created_at=self.clock.now())
        if payload.get("trace_id"):
            inc.trace_ids.append(payload["trace_id"])
        self._save(inc)
        self._timeline(inc.id, "created", f"Incident declared from alert {source}/{key} ({severity})", actor)
        return inc

    def create_manual(self, title: str, severity: str = "SEV3", tenant: str = "default",
                      service: str = "", impact_description: str = "",
                      impact: str = "medium", urgency: str = "medium", actor: str = "operator") -> Incident:
        inc = Incident(
            id=self.ids.next("inc"), title=title, severity=severity, status="triggered",
            source="manual", alert_key=self.ids.next("manual"),
            tenant=tenant, service=service, impact_description=impact_description,
            impact=impact, urgency=urgency, created_at=self.clock.now())
        self._save(inc)
        self._timeline(inc.id, "created", f"Incident declared manually ({severity})", actor)
        return inc

    def transition(self, incident_id: str, new_status: str, actor: str = "operator",
                   note: str = "") -> Incident:
        inc = self.get(incident_id)
        if new_status not in TRANSITIONS.get(inc.status, ()):
            raise InvalidTransitionError(f"illegal transition {inc.status} -> {new_status}")
        old = inc.status
        inc.status = new_status
        now = self.clock.now()
        if new_status == "acknowledged":
            inc.acknowledged_at = now
        elif new_status == "mitigated":
            inc.mitigated_at = now
        elif new_status == "resolved":
            inc.resolved_at = now
        elif new_status == "postmortem":
            inc.postmortem_at = now
        self._save(inc)
        message = f"Status changed {old} -> {new_status}"
        if note:
            message += f": {note}"
        self._timeline(inc.id, "transition", message, actor)
        return inc

    def add_note(self, incident_id: str, text: str, actor: str = "operator") -> None:
        self.get(incident_id)  # existence check
        self._timeline(incident_id, "note", text, actor)

    def attach_trace(self, incident_id: str, trace_id: str, actor: str = "operator") -> Incident:
        inc = self.get(incident_id)
        if trace_id not in inc.trace_ids:
            inc.trace_ids.append(trace_id)
            self._save(inc)
        self._timeline(incident_id, "trace", f"Trace attached: {trace_id}", actor)
        return inc

    def timeline(self, incident_id: str) -> list[TimelineEntry]:
        rows = self.conn.execute(
            "SELECT * FROM timeline WHERE incident_id=? ORDER BY id ASC", (incident_id,)).fetchall()
        return [TimelineEntry(id=r["id"], incident_id=r["incident_id"], ts=_parse(r["ts"]),
                              kind=r["kind"], message=r["message"], actor=r["actor"]) for r in rows]

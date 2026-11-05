import os

from fde_incident_response.clock import DeterministicClock
from fde_incident_response.demo import main, run_demo_pipeline
from fde_incident_response.logging import FileSink, StructuredLogger, parse_log_line


def test_demo_main_runs(capsys):
    main()
    out = capsys.readouterr().out
    assert "Trace trace-0001: 3 spans" in out
    assert "# Post-Mortem: API latency spike" in out
    assert "- Time to acknowledge: 300s" in out
    assert "- Time to mitigate: 1800s" in out
    assert "- Time to resolve: 3600s" in out


def test_pipeline_is_deterministic():
    _, tracer1, sink1, _ = run_demo_pipeline()
    _, tracer2, sink2, _ = run_demo_pipeline()
    assert sink1.lines == sink2.lines
    assert [(s.span_id, s.duration_seconds) for s in tracer1.spans] == \
           [(s.span_id, s.duration_seconds) for s in tracer2.spans]


def test_file_sink_roundtrip(tmp_path):
    path = str(tmp_path / "log.jsonl")
    logger = StructuredLogger("svc", FileSink(path), DeterministicClock())
    logger.warning("disk low")
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert len(lines) == 1
    assert parse_log_line(lines[0])["msg"] == "disk low"
    assert os.path.exists(path)

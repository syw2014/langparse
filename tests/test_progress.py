from dataclasses import asdict

import pytest

from langparse import AutoParser, ExcelParser, ProgressEvent
from langparse.cli import main
from langparse.progress import ProgressReporter
from langparse.services.parse_service import ParseService


def test_file_events_surround_result_and_do_not_change_output(sample_md_file):
    events = []
    baseline = AutoParser.parse_result(sample_md_file, chunk=True)
    parsed = AutoParser.parse_result(sample_md_file, chunk=True, progress_callback=events.append)
    assert asdict(parsed) == asdict(baseline)
    assert [(e.phase, e.state) for e in events] == [
        ("file", "running"),
        ("parsing", "running"),
        ("chunking", "running"),
        ("file", "completed"),
    ]
    assert all(e.source == str(sample_md_file) for e in events)
    assert all(isinstance(e, ProgressEvent) for e in events)


def test_failure_has_terminal_event_and_preserves_exception(tmp_path):
    events = []
    with pytest.raises(FileNotFoundError):
        AutoParser.parse_result(tmp_path / "missing.md", progress_callback=events.append)
    assert events[-1].phase == "file"
    assert events[-1].state == "failed"
    assert not any(e.state == "completed" for e in events)


def test_broken_observer_does_not_break_parse(sample_md_file):
    def broken(event):
        raise ValueError("observer failure")

    assert AutoParser.parse_result(sample_md_file, progress_callback=broken).markdown_content


def test_counts_have_phase_local_percentage_and_unknown_is_none():
    events = []
    reporter = ProgressReporter("file", events.append)
    reporter.emit("parsing")
    reporter.emit("parsing", completed_units=1, total_units=4, unit="pages")
    assert events[0].percent is None
    assert events[1].percent == 25.0


def test_callback_never_enters_engine_constructor(tmp_path, monkeypatch):
    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF-1.4")
    events = []

    class Engine:
        def process(self, file_path, **kwargs):
            assert kwargs["progress_callback"] == events.append
            return iter(())

    def create(name, **kwargs):
        assert "progress_callback" not in kwargs
        return Engine()

    service = ParseService()
    monkeypatch.setattr(service, "_create_engine", create)
    service.parse_result(path, progress_callback=events.append)
    assert events[-1].state == "completed"


def test_excel_stages_available_directly_and_via_facade(sample_excel_file):
    direct = []
    ExcelParser().parse_result(sample_excel_file, progress_callback=direct.append)
    assert [e.phase for e in direct] == ["extracting", "assembling", "rendering"]
    events = []
    AutoParser.parse_result(sample_excel_file, progress_callback=events.append)
    assert [e.phase for e in events] == [
        "file",
        "parsing",
        "extracting",
        "assembling",
        "rendering",
        "file",
    ]
    assert all(e.percent is None for e in direct)


def test_cli_progress_goes_to_stderr_only(sample_md_file, capsys):
    assert main(["parse", str(sample_md_file), "--format", "json", "--progress"]) == 0
    captured = capsys.readouterr()
    import json

    assert json.loads(captured.out)["engine"] == "markdown"
    assert "completed" in captured.err
    assert main(["parse", str(sample_md_file)]) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("method", ["parse_batch", "parse_batch_outputs"])
def test_legacy_batch_helpers_keep_callback_out_of_engine_config(
    sample_md_file, monkeypatch, method
):
    service = ParseService()
    events = []

    def create(name, **kwargs):
        assert "progress_callback" not in kwargs
        return object()

    monkeypatch.setattr(service, "_create_engine", create)
    getattr(service, method)([sample_md_file], progress_callback=events.append)
    assert events[-1].state == "completed"


def test_excel_fallback_completes_with_partial_quality(sample_excel_file, monkeypatch):
    from langparse.workbooks import assembly

    def fail(*args, **kwargs):
        raise ValueError("structural failure")

    monkeypatch.setattr(assembly, "assemble_workbook", fail)
    events = []
    result = AutoParser.parse_result(sample_excel_file, progress_callback=events.append)
    assert result.diagnostics.status == "partial"
    assert events[-1].state == "completed"
    assert events[-2].phase == "rendering"

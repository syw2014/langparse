from pathlib import Path
from threading import Event, Lock

import pytest

from langparse.progress import ProgressReporter
from langparse.services.batch_service import BatchParseService
from langparse.types import ParsedDocumentResult


class StubParser:
    def __init__(self, *, fail_setup=False, failed_sources=()):
        self.fail_setup = fail_setup
        self.failed_sources = failed_sources
        self.engine_kwargs = None

    def create_engine(self, engine_name, **kwargs):
        self.engine_kwargs = kwargs
        if self.fail_setup:
            raise ValueError("engine setup failed")
        return object()

    def parse_result(self, path, *, progress_callback=None, **kwargs):
        reporter = ProgressReporter(path, progress_callback)
        with reporter.operation("file"):
            if path.name in self.failed_sources:
                raise ValueError("parsing failed")
            return ParsedDocumentResult(
                source=str(path), filename=path.name, engine="simple", markdown_content=path.name
            )

    def render_output(self, parsed, fmt, **kwargs):
        return parsed.markdown_content


def files(tmp_path, *names):
    paths = [tmp_path / name for name in names]
    for path in paths:
        path.touch()
    return paths


def batch_events(events):
    return [event for event in events if event.phase == "batch"]


def test_parallel_progress_arrives_before_first_input_finishes_and_preserves_order(tmp_path):
    first_started = Event()
    second_reported = Event()
    callback_lock = Lock()
    callback_errors = []
    events = []

    class OrderedParser(StubParser):
        def parse_result(self, path, **kwargs):
            if path.name == "a.txt":
                first_started.set()
                assert second_reported.wait(5), "completed second input was not reported promptly"
            else:
                assert first_started.wait(5)
            return super().parse_result(path, **kwargs)

    def observe(event):
        if not callback_lock.acquire(blocking=False):
            callback_errors.append("callbacks ran concurrently")
            return
        try:
            events.append(event)
            if event.phase == "batch" and event.completed_units == 1:
                second_reported.set()
        finally:
            callback_lock.release()

    parser = OrderedParser()
    result = BatchParseService(parser).run(
        files(tmp_path, "a.txt", "b.txt"),
        output_dir=None,
        max_workers=2,
        collect_metrics=False,
        progress_callback=observe,
    )
    assert result.success_count == 2
    assert not callback_errors
    assert [Path(item.source).name for item in result.items] == ["a.txt", "b.txt"]
    assert result.rendered_outputs == ["a.txt", "b.txt"]
    assert parser.engine_kwargs == {}
    progress = batch_events(events)
    assert [event.completed_units for event in progress] == [0, 1, 2, 2]
    assert progress[-1].state == "completed"
    assert progress[-1].percent == 100
    assert all(event.source == "" and event.unit == "files" for event in progress)
    file_completions = [
        event for event in events if event.phase == "file" and event.state == "completed"
    ]
    assert Path(file_completions[0].source).name == "b.txt"


def test_skipped_and_failed_inputs_count_as_finished(tmp_path):
    paths = files(tmp_path, "a.txt", "b.txt")
    output = tmp_path / "out"
    output.mkdir()
    (output / "a.md").write_text("previous", encoding="utf-8")
    events = []
    result = BatchParseService(StubParser(failed_sources={"b.txt"})).run(
        paths,
        output_dir=output,
        max_workers=1,
        skip_existing=True,
        progress_callback=events.append,
    )
    assert [item.status for item in result.items] == ["skipped", "failed"]
    assert batch_events(events)[-1].completed_units == 2
    assert batch_events(events)[-1].state == "completed"
    item_events = [event for event in events if event.phase == "batch_item"]
    assert [(Path(event.source).name, event.state) for event in item_events] == [
        ("a.txt", "skipped"),
        ("b.txt", "failed"),
    ]
    assert (output / "a.md").read_text(encoding="utf-8") == "previous"


@pytest.mark.parametrize("failure", ["setup", "input", "parse", "output"])
def test_batch_failure_has_failed_terminal_event(tmp_path, monkeypatch, failure):
    paths = files(tmp_path, "a.txt")
    parser = StubParser(
        fail_setup=failure == "setup", failed_sources={"a.txt"} if failure == "parse" else ()
    )
    service = BatchParseService(parser)
    if failure == "input":
        paths = [tmp_path / "missing.txt"]
    if failure == "output":

        def fail_write(*args):
            raise OSError("disk full")

        monkeypatch.setattr(service, "_write_jsonl", fail_write)
    events = []
    with pytest.raises((ValueError, FileNotFoundError, OSError)):
        service.run(
            paths,
            output_dir=tmp_path / "out",
            max_workers=1,
            fail_fast=True,
            collect_metrics=False,
            progress_callback=events.append,
        )
    progress = batch_events(events)
    assert progress[-1].state == "failed"
    assert not any(event.state == "completed" for event in progress)
    assert progress[-1].completed_units == (1 if failure in {"parse", "output"} else 0)
    if failure == "parse":
        assert next(event for event in events if event.phase == "batch_item").state == "failed"


def test_output_failure_reports_failed_batch_item(tmp_path):
    paths = files(tmp_path, "a.txt")
    output = tmp_path / "out"
    output.mkdir()
    (output / "a.md").mkdir()
    events = []
    result = BatchParseService(StubParser()).run(
        paths, output_dir=output, collect_metrics=False, progress_callback=events.append
    )
    assert result.items[0].status == "failed"
    assert next(event for event in events if event.phase == "file" and event.state == "completed")
    assert next(event for event in events if event.phase == "batch_item").state == "failed"


def test_parallel_fail_fast_counts_workers_finished_during_shutdown(tmp_path):
    first_started = Event()
    failure_reported = Event()

    class FailingParser(StubParser):
        def parse_result(self, path, **kwargs):
            if path.name == "a.txt":
                first_started.set()
                assert failure_reported.wait(5)
            else:
                assert first_started.wait(5)
                raise ValueError("parse failed")
            return super().parse_result(path, **kwargs)

    events = []

    def observe(event):
        events.append(event)
        if event.phase == "batch_item" and event.state == "failed":
            failure_reported.set()

    with pytest.raises(ValueError, match="parse failed"):
        BatchParseService(FailingParser()).run(
            files(tmp_path, "a.txt", "b.txt"),
            output_dir=None,
            max_workers=2,
            fail_fast=True,
            collect_metrics=False,
            progress_callback=observe,
        )
    assert events[-1].phase == "batch"
    assert events[-1].state == "failed"
    assert events[-1].completed_units == 2


def test_empty_batch_reports_zero_of_zero(tmp_path):
    events = []
    result = BatchParseService(StubParser()).run(
        [], output_dir=None, progress_callback=events.append
    )
    assert result.items == []
    assert events[-1].state == "completed"
    assert events[-1].completed_units == events[-1].total_units == 0


def test_observer_failure_does_not_fail_batch(tmp_path):
    def broken_callback(event):
        raise RuntimeError("observer failed")

    result = BatchParseService(StubParser()).run(
        files(tmp_path, "a.txt"),
        output_dir=None,
        collect_metrics=False,
        progress_callback=broken_callback,
    )
    assert result.success_count == 1

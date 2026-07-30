import logging


def test_langparse_has_no_required_third_party_dependencies():
    """
    A parsing library should not force a logging framework on its host.

    Read from the installed distribution rather than pyproject.toml: it checks
    the artifact users actually get, and tomllib is stdlib only on 3.11+ while
    this package supports 3.10.
    """
    import importlib.metadata as metadata

    requirements = metadata.requires("langparse") or []
    required = [line for line in requirements if "extra ==" not in line]

    assert required == []


def test_library_logger_is_silent_by_default(caplog):
    """A NullHandler keeps import-time config problems off the host's stderr
    unless the host opts in to logging."""
    from langparse.logging import get_logger

    logger = get_logger("test")

    assert any(isinstance(h, logging.NullHandler) for h in logging.getLogger("langparse").handlers)
    assert logger.name.startswith("langparse")


def test_bad_config_file_logs_a_warning_instead_of_printing(tmp_path, monkeypatch, caplog, capsys):
    from langparse.config import Config

    home = tmp_path / "home"
    (home / ".langparse").mkdir(parents=True)
    (home / ".langparse" / "config.json").write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr("pathlib.Path.home", lambda: home)

    with caplog.at_level(logging.WARNING, logger="langparse"):
        Config()

    assert "Failed to load config file" in caplog.text
    assert capsys.readouterr().out == ""

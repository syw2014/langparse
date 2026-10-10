from langparse.errors import ErrorType, classify_exception


def test_classify_file_not_found():
    error = classify_exception(FileNotFoundError("missing.pdf"))

    assert error.error_type == ErrorType.FILE_NOT_FOUND
    assert "missing.pdf" in error.message


def test_classify_dependency_missing_from_import_error():
    error = classify_exception(ImportError("Please install `pdfplumber`."))

    assert error.error_type == ErrorType.DEPENDENCY_MISSING
    assert "pdfplumber" in error.message


def test_classify_cuda_unavailable_as_engine_unavailable():
    error = classify_exception(RuntimeError("CUDA was requested for MinerU but is not available."))

    assert error.error_type == ErrorType.ENGINE_UNAVAILABLE
    assert "CUDA" in error.message


def test_classify_unknown_runtime_error_as_parse_failed():
    error = classify_exception(RuntimeError("unexpected parser crash"))

    assert error.error_type == ErrorType.PARSE_FAILED
    assert "unexpected parser crash" in error.message


def test_timeout_types_do_not_require_message_keywords():
    from subprocess import TimeoutExpired
    from urllib.error import URLError

    for exc in (TimeoutError(), TimeoutExpired("worker", 1), URLError(TimeoutError())):
        assert classify_exception(exc).error_type == ErrorType.ENGINE_TIMEOUT


def test_timeout_configuration_or_filename_is_not_execution_timeout():
    for exc in (ValueError("invalid timeout option"), RuntimeError("timeout.pdf is corrupt")):
        assert classify_exception(exc).error_type == ErrorType.PARSE_FAILED


def test_wrapped_timeout_preserves_outer_error_message():
    try:
        try:
            raise TimeoutError()
        except TimeoutError as inner:
            raise RuntimeError("PDF request failed") from inner
    except RuntimeError as exc:
        result = classify_exception(exc)
    assert result.error_type == ErrorType.ENGINE_TIMEOUT
    assert result.message == "PDF request failed"


def test_backend_text_timeout_fallback_remains_supported():
    assert (
        classify_exception(RuntimeError("request timed out")).error_type == ErrorType.ENGINE_TIMEOUT
    )

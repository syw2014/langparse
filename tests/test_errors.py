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

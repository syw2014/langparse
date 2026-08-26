# Task 1 Report: Define the typed model policy and provider port

## Implemented behavior

- Added the frozen, typed workbook-model data contract: model modes, policy limits, model identity, region cues/choices/cases, model requests/replies/decisions, call audits, and resolution batches.
- Added the `WorkbookStructureModelAdapter` provider protocol with `identity` and keyword-only timeout completion.
- Added the workbook model error hierarchy, including required-mode unresolved diagnostics carrying case IDs and `ParseDiagnostics`.
- Added frozen `WorkbookDisambiguation` configuration with `off`, `auto`, and `required` constructors. Modes are normalized through `WorkbookModelMode`; invalid adapter/mode combinations fail during construction.
- Preserved the explicit opt-in/no-network contract: no provider implementation, cache, transport, CLI flag, or environment lookup was added.
- `WorkbookModelRequest.choice_ids_by_case` is an immutable tuple registry for later strict response decoding.

## Files

- `langparse/workbooks/modeling/__init__.py`
- `langparse/workbooks/modeling/types.py`
- `langparse/workbooks/modeling/ports.py`
- `langparse/workbooks/modeling/policy.py`
- `tests/test_workbook_model_policy.py`

## RED

Command:

```text
/Users/jerryshi/Desktop/workspace/research/projects/langparse/.venv/bin/python -m pytest tests/test_workbook_model_policy.py -q
```

Result: collection failed as expected with:

```text
ModuleNotFoundError: No module named 'langparse.workbooks.modeling'
```

## GREEN and focused verification

Command:

```text
/Users/jerryshi/Desktop/workspace/research/projects/langparse/.venv/bin/python -m pytest tests/test_workbook_model_policy.py -q
```

Result:

```text
5 passed in 0.17s
```

Ruff commands:

```text
/Users/jerryshi/Desktop/workspace/research/projects/langparse/.venv/bin/ruff check langparse/workbooks/modeling tests/test_workbook_model_policy.py
/Users/jerryshi/Desktop/workspace/research/projects/langparse/.venv/bin/ruff format --check langparse/workbooks/modeling tests/test_workbook_model_policy.py
```

Result:

```text
All checks passed!
5 files already formatted
```

The initial format check identified one wrapping change in `policy.py`; `ruff format` applied it and the final format check passed.

## Full-suite result

Commands:

```text
/Users/jerryshi/Desktop/workspace/research/projects/langparse/.venv/bin/python -m pytest -q
git diff --check
```

Result:

```text
378 passed in 8.19s
```

`git diff --check` produced no diagnostics.

## Self-review

- All requested public types, constants, protocol methods, exception classes, and policy defaults match the task brief.
- All data contracts are frozen dataclasses; configuration is frozen and rejects invalid adapter combinations at construction.
- No provider-specific dependency or implementation leaked into the public seam.
- Focused and full tests pass, and the final tree is Ruff-clean and whitespace-clean.

## Concerns

No known concerns within Task 1 scope. Provider behavior, validation, caching, and runtime integration remain intentionally deferred to later tasks.

## Commits

- `11d8d98d8851a3ea11177a33799975695255afa6` — `feat: define workbook model policy`

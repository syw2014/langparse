# Workbook Ambiguity Seed Golden Set

This directory provides a minimal, inspectable seed dataset for testing the Phase 4B-1 evaluation framework and rule baselines.

## Dataset Information

- **Dataset ID**: `workbook-region-seed`
- **Dataset Version**: `1`
- **Split**: `tuning`
- **Manifest**: `public-manifest.json`

## Disclaimers & Usage Boundary

> [!WARNING]
> This seed dataset is intended solely for verifying the functionality of the evaluation harness, schema loaders, drift detectors, and metric calculations. It **does not** constitute statistical or empirical evidence of production model performance.

## Run the Seed Benchmark

From the repository root:

```bash
uv run langparse benchmark-workbook-ambiguity \
  samples/workbook_ambiguity/public-manifest.json \
  --output-dir reports/workbook-ambiguity
```

Live provider evaluation is separately installed and explicitly enabled:

```bash
uv sync --extra model
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o-mini"

uv run langparse benchmark-workbook-ambiguity private-manifest.json \
  --model \
  --output-dir reports/workbook-ambiguity
```

Do not put API keys in command-line arguments. The built-in tuning seed cannot
make `production_ready` true: the release gate also requires a representative
holdout with at least 30 ambiguous cases and separate operational staging
evidence. Report directories are content-addressed and must not be edited after
publication.

## Samples

1. `sparse_region.xlsx` (`sparse-region-fixable`):
   - Cohort: `ambiguous`
   - Description: A sparse candidate region where deterministic rule baseline outputs `unclassified`, while human ground truth is `text`. This verifies that the baseline can accurately record "rule error with fix opportunity".
2. `risk_region.xlsx` (`sparse-region-risk`):
   - Cohort: `ambiguous`
   - Description: An ambiguous candidate region where deterministic rule fallback and ground truth are both `unclassified`. This tests the evaluator's ability to capture introduced-error risk when alternative choices are selected.
3. `clear_table.xlsx` (`clear-logical-table`):
   - Cohort: `clear_no_call`
   - Description: A standard, clean 2D table requiring zero model adapter requests.

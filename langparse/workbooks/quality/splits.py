"""Enforce tuning/holdout separation for workbook quality datasets.

A ``split`` label in a manifest only states intent. These checks prove the
intent: a holdout dataset must not reuse any workbook that a tuning dataset
already exposed, by content hash or by source location. The returned record is
privacy-safe provenance — dataset identifiers, digests and counts only, never
sample paths or cell content — so it can be embedded in a published report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langparse.workbooks.quality.schema import WorkbookQualityManifest

SPLIT_ISOLATION_SCHEMA_VERSION = 1


class WorkbookSplitIsolationError(ValueError):
    """Raised when a holdout dataset is not separated from tuning data."""


@dataclass(frozen=True)
class TuningDatasetReference:
    dataset_id: str
    dataset_version: str
    dataset_digest: str
    sample_count: int


@dataclass(frozen=True)
class SplitIsolationRecord:
    schema_version: int
    holdout_dataset_id: str
    holdout_dataset_version: str
    holdout_dataset_digest: str
    holdout_sample_count: int
    tuning_datasets: tuple[TuningDatasetReference, ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "holdout_dataset_id": self.holdout_dataset_id,
            "holdout_dataset_version": self.holdout_dataset_version,
            "holdout_dataset_digest": self.holdout_dataset_digest,
            "holdout_sample_count": self.holdout_sample_count,
            "tuning_datasets": [
                {
                    "dataset_id": reference.dataset_id,
                    "dataset_version": reference.dataset_version,
                    "dataset_digest": reference.dataset_digest,
                    "sample_count": reference.sample_count,
                }
                for reference in self.tuning_datasets
            ],
        }


def verify_split_isolation(
    holdout: WorkbookQualityManifest,
    tuning: tuple[WorkbookQualityManifest, ...],
) -> SplitIsolationRecord:
    """Verify that ``holdout`` shares no workbook with any ``tuning`` dataset.

    Raises ``WorkbookSplitIsolationError`` on a wrong split label, an empty
    reference set, a repeated tuning dataset, or a workbook that both splits
    reach by content hash or by resolved source path.
    """
    if holdout.split != "holdout":
        raise WorkbookSplitIsolationError(
            f"Evaluated manifest must declare split holdout, got {holdout.split}"
        )
    if not tuning:
        raise WorkbookSplitIsolationError(
            "Split isolation requires at least one tuning manifest to compare against"
        )

    seen_datasets: set[tuple[str, str]] = set()
    for manifest in tuning:
        if manifest.split != "tuning":
            raise WorkbookSplitIsolationError(
                f"Reference manifest {manifest.dataset_id} must declare split tuning, "
                f"got {manifest.split}"
            )
        identity = (manifest.dataset_id, manifest.dataset_version)
        if identity in seen_datasets:
            raise WorkbookSplitIsolationError(
                f"Duplicate tuning dataset reference: {manifest.dataset_id}"
                f"@{manifest.dataset_version}"
            )
        seen_datasets.add(identity)

    tuning_hashes = {
        sample.sha256: (manifest.dataset_id, sample.sample_id)
        for manifest in tuning
        for sample in manifest.samples
    }
    tuning_paths = {
        str((manifest.source_root / sample.path).resolve()): (
            manifest.dataset_id,
            sample.sample_id,
        )
        for manifest in tuning
        for sample in manifest.samples
    }

    for sample in holdout.samples:
        leak = tuning_hashes.get(sample.sha256)
        if leak is not None:
            raise WorkbookSplitIsolationError(
                f"Holdout sample {sample.sample_id} repeats tuning content from {leak[0]}/{leak[1]}"
            )
        resolved = str((holdout.source_root / sample.path).resolve())
        leak = tuning_paths.get(resolved)
        if leak is not None:
            raise WorkbookSplitIsolationError(
                f"Holdout sample {sample.sample_id} reuses the tuning source file of "
                f"{leak[0]}/{leak[1]}"
            )

    return SplitIsolationRecord(
        schema_version=SPLIT_ISOLATION_SCHEMA_VERSION,
        holdout_dataset_id=holdout.dataset_id,
        holdout_dataset_version=holdout.dataset_version,
        holdout_dataset_digest=holdout.dataset_digest,
        holdout_sample_count=len(holdout.samples),
        tuning_datasets=tuple(
            sorted(
                (
                    TuningDatasetReference(
                        dataset_id=manifest.dataset_id,
                        dataset_version=manifest.dataset_version,
                        dataset_digest=manifest.dataset_digest,
                        sample_count=len(manifest.samples),
                    )
                    for manifest in tuning
                ),
                key=lambda reference: (reference.dataset_id, reference.dataset_version),
            )
        ),
    )

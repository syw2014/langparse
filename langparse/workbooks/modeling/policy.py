from __future__ import annotations

from dataclasses import dataclass

from .ports import WorkbookModelConfigurationError, WorkbookStructureModelAdapter
from .types import WorkbookModelMode, WorkbookModelPolicy


@dataclass(frozen=True)
class WorkbookDisambiguation:
    mode: WorkbookModelMode = WorkbookModelMode.OFF
    adapter: WorkbookStructureModelAdapter | None = None
    policy: WorkbookModelPolicy = WorkbookModelPolicy()

    def __post_init__(self) -> None:
        mode = WorkbookModelMode(self.mode)
        object.__setattr__(self, "mode", mode)

        if self.policy is None:
            object.__setattr__(self, "policy", WorkbookModelPolicy())
        elif not isinstance(self.policy, WorkbookModelPolicy):
            raise WorkbookModelConfigurationError("policy must be a WorkbookModelPolicy")

        if mode is WorkbookModelMode.OFF and self.adapter is not None:
            raise WorkbookModelConfigurationError(
                "off workbook disambiguation cannot carry an adapter"
            )
        if mode is WorkbookModelMode.AUTO and self.adapter is None:
            raise WorkbookModelConfigurationError(
                "auto workbook disambiguation requires an adapter"
            )
        if mode is WorkbookModelMode.REQUIRED and self.adapter is None:
            raise WorkbookModelConfigurationError(
                "required workbook disambiguation requires an adapter"
            )

    @classmethod
    def off(cls) -> WorkbookDisambiguation:
        return cls(mode=WorkbookModelMode.OFF)

    @classmethod
    def auto(
        cls,
        adapter: WorkbookStructureModelAdapter,
        *,
        policy: WorkbookModelPolicy | None = None,
    ) -> WorkbookDisambiguation:
        return cls(
            mode=WorkbookModelMode.AUTO,
            adapter=adapter,
            policy=WorkbookModelPolicy() if policy is None else policy,
        )

    @classmethod
    def required(
        cls,
        adapter: WorkbookStructureModelAdapter,
        *,
        policy: WorkbookModelPolicy | None = None,
    ) -> WorkbookDisambiguation:
        return cls(
            mode=WorkbookModelMode.REQUIRED,
            adapter=adapter,
            policy=WorkbookModelPolicy() if policy is None else policy,
        )

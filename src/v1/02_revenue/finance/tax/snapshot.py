"""An organization's tax configuration as it stood on one date: what the engine reads."""

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional, TypeVar

from pydantic import BaseModel

from finance.errors import entry_not_effective
from finance.tax.config_schema import (
    CategoryData,
    ComponentData,
    JurisdictionData,
    RateData,
    RegimeData,
    RuleData,
    SeriesTemplateData,
    WithholdingSectionData,
    validate_entry_data,
)

DataT = TypeVar("DataT", bound=BaseModel)


@dataclass(frozen=True)
class ConfigEntry:
    kind: str
    code: str
    effective_from: date
    effective_to: Optional[date]
    data: BaseModel

    def in_effect_on(self, day: date) -> bool:
        return self.effective_from <= day and (self.effective_to is None or day < self.effective_to)


@dataclass(frozen=True)
class ConfigSnapshot:
    as_of: date
    revision: int
    _by_kind: dict[str, dict[str, ConfigEntry]] = field(default_factory=dict)

    @classmethod
    def build(cls, as_of: date, revision: int, entries: Iterable[ConfigEntry]) -> "ConfigSnapshot":
        by_kind: dict[str, dict[str, ConfigEntry]] = {}
        for entry in entries:
            if entry.in_effect_on(as_of):
                by_kind.setdefault(entry.kind, {})[entry.code] = entry
        return cls(as_of=as_of, revision=revision, _by_kind=by_kind)

    @classmethod
    def from_raw(cls, as_of: date, revision: int, rows: Iterable[tuple[str, str, date, Optional[date], dict]]) -> "ConfigSnapshot":
        entries = (
            ConfigEntry(kind, code, starts, ends, validate_entry_data(kind, data))
            for kind, code, starts, ends, data in rows
        )
        return cls.build(as_of, revision, entries)

    def find(self, kind: str, code: str) -> Optional[ConfigEntry]:
        return self._by_kind.get(kind, {}).get(code)

    def entries(self, kind: str) -> list[ConfigEntry]:
        return sorted(self._by_kind.get(kind, {}).values(), key=lambda entry: entry.code)

    def require(self, kind: str, code: str, schema: type[DataT]) -> DataT:
        entry = self.find(kind, code)
        if entry is None:
            raise entry_not_effective(kind, code, self.as_of.isoformat())
        return entry.data  # type: ignore[return-value]

    def regime(self, code: str) -> RegimeData:
        return self.require("regime", code, RegimeData)

    def component(self, code: str) -> ComponentData:
        return self.require("component", code, ComponentData)

    def rate(self, code: str) -> RateData:
        return self.require("rate", code, RateData)

    def category(self, code: str) -> CategoryData:
        return self.require("category", code, CategoryData)

    def series_template(self, doc_type: str) -> Optional[SeriesTemplateData]:
        entry = self.find("series_template", doc_type)
        return entry.data if entry else None  # type: ignore[return-value]

    def jurisdiction(self, regime: str, code: str) -> Optional[JurisdictionData]:
        entry = self.find("jurisdiction", code)
        if entry is None or entry.data.regime != regime:  # type: ignore[attr-defined]
            return None
        return entry.data  # type: ignore[return-value]

    def rules(self, regime: str) -> list[tuple[str, RuleData]]:
        return [(entry.code, entry.data) for entry in self.entries("rule") if entry.data.regime == regime]  # type: ignore[attr-defined]

    def categories(self, regime: str) -> list[tuple[str, CategoryData]]:
        return [(entry.code, entry.data) for entry in self.entries("category") if entry.data.regime == regime]  # type: ignore[attr-defined]

    def withholding_section(self, code_or_alias: str) -> Optional[tuple[str, WithholdingSectionData]]:
        """A section by its code, or by any alias (an old statute's section number)."""
        direct = self.find("withholding_section", code_or_alias)
        if direct is not None:
            return direct.code, direct.data  # type: ignore[return-value]
        wanted = code_or_alias.strip().upper()
        for entry in self.entries("withholding_section"):
            data: WithholdingSectionData = entry.data  # type: ignore[assignment]
            if wanted in (alias.upper() for alias in data.aliases):
                return entry.code, data
        return None

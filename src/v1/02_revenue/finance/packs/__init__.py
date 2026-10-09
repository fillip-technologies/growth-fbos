"""
Packs: versioned, code-reviewed tax configuration shipped with the service.

A pack file is `<code>.v<version>.yaml`. Its entries are grouped by kind; each entry has a
`code`, an `effective_from`, an optional `effective_to`, and the kind's data fields inline.
Packs are copied into an organization's configuration on first use and upgraded only when an
admin reviews the changes and applies them (`finance/packs/applier.py`).
"""

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Optional

import yaml

from finance.errors import FinanceNotFoundError, TaxConfigError
from finance.tax.config_schema import validate_entry_data

PACK_DIR = Path(__file__).resolve().parent
_PACK_FILE = re.compile(r"^(?P<code>[a-z0-9_]+)\.v(?P<version>\d+)\.yaml$")


@dataclass(frozen=True)
class PackEntry:
    kind: str
    code: str
    effective_from: date
    effective_to: Optional[date]
    data: dict[str, Any]

    @property
    def key(self) -> tuple[str, str, date]:
        return self.kind, self.code, self.effective_from


@dataclass(frozen=True)
class Pack:
    code: str
    version: int
    title: str
    description: str
    entries: tuple[PackEntry, ...]

    @property
    def origin(self) -> str:
        return f"pack:{self.code}@{self.version}"


def _as_date(value: Any, where: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise TaxConfigError("TAX_PACK_INVALID", f"{where}: '{value}' is not a date") from error


def parse_pack(document: dict[str, Any], source: str) -> Pack:
    entries: list[PackEntry] = []
    for kind, items in (document.get("entries") or {}).items():
        for position, item in enumerate(items or []):
            fields = dict(item)
            where = f"{source} {kind}[{position}]"
            code = str(fields.pop("code"))
            effective_from = _as_date(fields.pop("effective_from"), where)
            raw_end = fields.pop("effective_to", None)
            effective_to = _as_date(raw_end, where) if raw_end is not None else None
            validated = validate_entry_data(kind, fields)
            # Stored as JSON: keep what was validated, with decimals as strings.
            entries.append(PackEntry(kind, code, effective_from, effective_to, validated.model_dump(mode="json")))
    return Pack(
        code=document["pack"],
        version=int(document["version"]),
        title=document.get("title", document["pack"]),
        description=document.get("description", ""),
        entries=tuple(entries),
    )


@lru_cache(maxsize=None)
def load_packs() -> dict[str, dict[int, Pack]]:
    """Every pack file shipped with the service: {code: {version: pack}}."""
    packs: dict[str, dict[int, Pack]] = {}
    for path in sorted(PACK_DIR.glob("*.yaml")):
        match = _PACK_FILE.match(path.name)
        if match is None:
            raise TaxConfigError("TAX_PACK_INVALID", f"Pack file '{path.name}' is not named <code>.v<version>.yaml")
        with path.open(encoding="utf-8") as handle:
            pack = parse_pack(yaml.safe_load(handle), path.name)
        if pack.code != match["code"] or pack.version != int(match["version"]):
            raise TaxConfigError("TAX_PACK_INVALID", f"Pack file '{path.name}' declares {pack.code} v{pack.version}")
        packs.setdefault(pack.code, {})[pack.version] = pack
    return packs


def get_pack(code: str, version: Optional[int] = None) -> Pack:
    versions = load_packs().get(code)
    if not versions:
        raise FinanceNotFoundError("TAX_PACK_NOT_FOUND", f"There is no tax pack '{code}'")
    chosen = max(versions) if version is None else version
    if chosen not in versions:
        raise FinanceNotFoundError("TAX_PACK_NOT_FOUND", f"Tax pack '{code}' has no version {chosen}")
    return versions[chosen]

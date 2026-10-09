"""
Diffing a pack version against an organization's configuration, and applying it.

Entries are matched on (kind, code, effective_from). What happens to each:
- add: the pack has it, the organization doesn't.
- update: both have it, it differs, and the organization never edited it.
- conflict: it differs (or the pack dropped it) but the organization edited it. Kept as is
  unless the admin lists it in `overwrite`.
- retire: the organization has it from an earlier version of this pack, the new version
  dropped it. A future entry is removed; one already in effect stops today.
- unchanged.
"""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal, Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from finance.packs import Pack, PackEntry
from finance.tax.store import check_no_overlaps, load_entries, record_revision
from models.tax_config import TaxConfigEntry, TaxPackApplication

ChangeAction = Literal["add", "update", "conflict", "retire", "unchanged"]
EntryKey = tuple[str, str, date]


@dataclass(frozen=True)
class PackChange:
    action: ChangeAction
    kind: str
    code: str
    effective_from: date
    current: Optional[dict[str, Any]]
    proposed: Optional[dict[str, Any]]
    reason: Optional[str] = None

    @property
    def key(self) -> EntryKey:
        return self.kind, self.code, self.effective_from

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _shape(effective_to: Optional[date], data: dict[str, Any]) -> dict[str, Any]:
    return {"effective_to": effective_to.isoformat() if effective_to else None, "data": data}


def _row_key(row: TaxConfigEntry) -> EntryKey:
    return row.kind, row.code, row.effective_from


def plan_pack(pack: Pack, existing: list[TaxConfigEntry], today: date) -> list[PackChange]:
    by_key = {_row_key(row): row for row in existing}
    changes: list[PackChange] = []
    for entry in pack.entries:
        changes.append(_plan_entry(entry, by_key.get(entry.key), today))

    pack_keys = {entry.key for entry in pack.entries}
    own_origin = f"pack:{pack.code}@"
    for row in existing:
        if not row.origin.startswith(own_origin) or _row_key(row) in pack_keys:
            continue
        current = _shape(row.effective_to, row.data)
        if row.locally_modified:
            changes.append(PackChange("conflict", row.kind, row.code, row.effective_from, current, None,
                                      "dropped from the pack, but edited in this organization"))
        else:
            changes.append(PackChange("retire", row.kind, row.code, row.effective_from, current, None))
    return changes


def _plan_entry(entry: PackEntry, row: Optional[TaxConfigEntry], today: date) -> PackChange:
    proposed = _shape(entry.effective_to, entry.data)
    if row is None:
        return PackChange("add", entry.kind, entry.code, entry.effective_from, None, proposed)
    current = _shape(row.effective_to, row.data)
    if current == proposed:
        return PackChange("unchanged", entry.kind, entry.code, entry.effective_from, current, proposed)
    if row.locally_modified:
        return PackChange("conflict", entry.kind, entry.code, entry.effective_from, current, proposed,
                          "edited in this organization")
    reason = "changes an entry already in effect" if row.effective_from <= today else None
    return PackChange("update", entry.kind, entry.code, entry.effective_from, current, proposed, reason)


def summarize(changes: list[PackChange]) -> dict[str, int]:
    counts = {action: 0 for action in ("add", "update", "conflict", "retire", "unchanged")}
    for change in changes:
        counts[change.action] += 1
    return counts


async def apply_pack(
    session: AsyncSession,
    org_id: uuid.UUID,
    pack: Pack,
    user_id: Optional[uuid.UUID],
    today: date,
    overwrite: frozenset[EntryKey] = frozenset(),
) -> TaxPackApplication:
    existing = await load_entries(session, org_id)
    by_key = {_row_key(row): row for row in existing}
    pack_entries = {entry.key: entry for entry in pack.entries}
    changes = plan_pack(pack, existing, today)

    for change in changes:
        action = change.action
        if action == "conflict" and change.key in overwrite:
            action = "update" if change.proposed is not None else "retire"
        if action == "add":
            entry = pack_entries[change.key]
            session.add(TaxConfigEntry(
                organization_id=org_id, kind=entry.kind, code=entry.code, effective_from=entry.effective_from,
                effective_to=entry.effective_to, data=entry.data, origin=pack.origin, created_by=user_id,
            ))
        elif action == "update":
            row, entry = by_key[change.key], pack_entries[change.key]
            row.data, row.effective_to = entry.data, entry.effective_to
            row.origin, row.locally_modified = pack.origin, False
            row.version += 1
        elif action == "retire":
            row = by_key[change.key]
            if row.effective_from >= today:
                await session.delete(row)
            elif row.effective_to is None or row.effective_to > today:
                row.effective_to = today
                row.version += 1
    await session.flush()
    check_no_overlaps(await load_entries(session, org_id))

    counts = summarize(changes)
    summary = ", ".join(f"{count} {action}" for action, count in counts.items() if count and action != "unchanged")
    revision = await record_revision(
        session, org_id, user_id, pack.origin, f"Applied {pack.title} v{pack.version}: {summary or 'no changes'}"
    )
    application = TaxPackApplication(
        organization_id=org_id, pack_code=pack.code, pack_version=pack.version, revision=revision,
        summary=counts, applied_by=user_id,
    )
    session.add(application)
    await session.flush()
    return application

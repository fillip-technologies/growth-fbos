"""The packs shipped with the service are valid on every date that matters to them."""
from datetime import date

import pytest

from finance.packs import load_packs
from finance.tax.lint import lint_snapshot
from finance.tax.periods import find_overlaps
from finance.tax.snapshot import ConfigSnapshot

ALL_ENTRIES = [entry for versions in load_packs().values() for pack in versions.values() for entry in pack.entries]


def boundary_dates() -> list[date]:
    """Every date an entry starts or ends, plus the day before each: where mistakes hide."""
    days: set[date] = set()
    for entry in ALL_ENTRIES:
        for day in (entry.effective_from, entry.effective_to):
            if day is not None:
                days.add(day)
                days.add(date.fromordinal(day.toordinal() - 1))
    return sorted(days)


def test_every_pack_loads_with_valid_entries():
    packs = load_packs()
    assert {"core", "in_gst", "in_itd"} <= set(packs)


def test_no_two_entries_of_one_kind_and_code_overlap_within_the_latest_packs():
    latest = [entry for versions in load_packs().values() for entry in versions[max(versions)].entries]
    assert find_overlaps((entry.kind, entry.code, entry.effective_from, entry.effective_to) for entry in latest) == []


@pytest.mark.parametrize("day", boundary_dates(), ids=str)
def test_every_reference_resolves_on_every_boundary_date(day: date):
    snapshot = ConfigSnapshot.from_raw(
        day, 1, [(entry.kind, entry.code, entry.effective_from, entry.effective_to, entry.data) for entry in ALL_ENTRIES]
    )
    # Before a regime starts nothing of it is in effect, so there is nothing to resolve.
    assert lint_snapshot(snapshot) == set()

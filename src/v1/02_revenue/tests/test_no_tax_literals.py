"""
Tax facts live in packs and configuration, never in code. This scans the finance package and
the billing services for the kinds of values that used to be hardcoded (a GSTIN, a GST state
code as a default, a GST rate, a fiscal-year label, a TDS section number) and fails when one
comes back. Packs (finance/packs/*.yaml), migrations and tests are where such values belong.
"""
from pathlib import Path
import re

SERVICE_ROOT = Path(__file__).resolve().parent.parent
SCANNED = [
    *sorted((SERVICE_ROOT / "finance").rglob("*.py")),
    *[SERVICE_ROOT / "services" / name for name in (
        "tax_service.py", "tax_config_service.py", "invoice_service.py", "quotation_service.py", "payment_service.py",
        "billing_schedule_service.py", "receivables_service.py", "offering_service.py", "collection_service.py",
    )],
]

FORBIDDEN = {
    "a GSTIN": re.compile(r"""["'][0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]["']"""),
    "a GST state code used as a value": re.compile(r"""(?:==|=|,|\()\s*["'](?:0[1-9]|[1-3][0-9])["']"""),
    "a GST rate": re.compile(r"""(?:gst|rate|tax)[a-z_]*\s*(?:=|==|\()\s*(?:Decimal\()?["']?(?:5|12|18|28|40)(?:\.0+)?["']?\)?(?![\d.])""", re.IGNORECASE),
    # Two-digit year pairs from 2017 on ("26-27"); MM-DD values like "01-01" are not years.
    "a fiscal-year label": re.compile(r"""["'](?:1[7-9]|[2-9][0-9])-(?:1[8-9]|[2-9][0-9])["']"""),
    "a TDS section number": re.compile(r"""["']19[0-9][A-Z]{0,2}(?:\([a-z]+\))?["']"""),
}


def test_finance_code_names_no_tax_facts():
    found = []
    for path in SCANNED:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for what, pattern in FORBIDDEN.items():
                if pattern.search(line):
                    found.append(f"{path.relative_to(SERVICE_ROOT)}:{line_no}: {what}: {line.strip()}")
    assert found == [], "Move these into a pack or the tax configuration:\n" + "\n".join(found)


def test_the_scan_catches_what_it_is_meant_to():
    samples = {
        "a GSTIN": 'supplier_gstin = "29AABCF9876L1Z3"',
        "a GST state code used as a value": 'place_of_supply = addr.get("state_code", "29")',
        "a GST rate": 'gst_rate = Decimal("18.0")',
        "a fiscal-year label": 'fy = "26-27"',
        "a TDS section number": 'section = "194J"',
    }
    for what, sample in samples.items():
        assert FORBIDDEN[what].search(sample), what

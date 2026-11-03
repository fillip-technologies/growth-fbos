"""The CEO Command Center's codes: in the catalog, and in no preset but admin (the administrator grants them)."""
from services.permission_catalog import PERMISSION_CATALOG, member_permission_codes

CEO_CODES = {
    "revenue.summary.read",
    "delivery.summary.read",
    "people.summary.read",
    "management.summary.read",
    "assets.summary.read",
    "insight.ceo_dashboard.read",
    "insight.ceo_dashboard.financials",
}


def test_ceo_codes_are_in_the_catalog():
    assert CEO_CODES <= {code for code, _, _ in PERMISSION_CATALOG}


def test_members_do_not_get_company_wide_totals():
    members = set(member_permission_codes([code for code, _, _ in PERMISSION_CATALOG]))
    assert not CEO_CODES & members

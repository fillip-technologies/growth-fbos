"""
One-off: open leads whose owner is not an active person of their organization (leads added
without an owner used to get a random id) go back to the unclaimed leads.

    python unclaim_unknown_owners.py                 # report only: which owner ids, how many leads
    python unclaim_unknown_owners.py --apply         # do it, for every organization
    python unclaim_unknown_owners.py --org <uuid>    # one organization (with or without --apply)

Each changed lead gets a `released` line in its history. Safe to repeat: a second run finds
nothing. Leads of people who have left (deactivated) are reported too; run it after the
migration `f3a9c1e7b5d2`.
"""

import argparse
import asyncio
import uuid

import httpx

from config import settings
from database.session import async_session_factory, dispose_engine
from services.identity_client import IdentityClient
from services.lead_owner_cleanup import unclaim_unknown_owners


async def main(organization_id: uuid.UUID | None, apply: bool) -> None:
    async with httpx.AsyncClient(base_url=settings.identity_service_url, timeout=settings.identity_timeout_seconds) as http:
        identity = IdentityClient(http, settings.internal_service_token)
        async with async_session_factory() as session:
            report = await unclaim_unknown_owners(session, identity, organization_id, apply)
    verb = "made unclaimed" if apply else "would be made unclaimed (report only; add --apply)"
    print(f"{report.checked} open lead(s) with an owner checked; {report.unclaimed} {verb}")
    for owner_id, count in sorted(report.unknown_owners.items(), key=lambda item: -item[1]):
        print(f"  owner {owner_id}: {count} lead(s)")
    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", type=uuid.UUID, default=None, help="only this organization")
    parser.add_argument("--apply", action="store_true", help="change the leads (default: report only)")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.org, arguments.apply))

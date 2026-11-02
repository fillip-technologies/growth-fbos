"""
One-off: let People manage the roles employees hold today, so an approved role change replaces them.

    python adopt_roles.py --dry-run          # how many employees and roles would be taken over
    python adopt_roles.py                    # do it, for every organization
    python adopt_roles.py --org <uuid>       # one organization

Safe to repeat: what was taken over is no longer held by hand, so a second run finds nothing. Run it after the
migrations and before turning on role changes that carry roles.
"""

import argparse
import asyncio
import uuid

import httpx

from config import settings
from database.session import AsyncSessionLocal, dispose_engine
from services.identity_client import IdentityClient
from services.role_adoption import adopt_current_roles


async def main(organization_id, dry_run: bool) -> None:
    async with httpx.AsyncClient(base_url=settings.identity_service_url, timeout=settings.identity_timeout_seconds) as http:
        identity = IdentityClient(http, settings.internal_service_token)
        async with AsyncSessionLocal() as session:
            report = await adopt_current_roles(session, identity, organization_id, dry_run)
    verb = "would be taken over" if dry_run else "taken over"
    print(f"{report.adopted} employee(s), {report.roles} role(s) {verb}")
    print(f"skipped: {report.skipped_no_roles} with no hand-granted role")
    for note in report.notes:
        print(f"note: {note}")
    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", type=uuid.UUID, default=None, help="only this organization")
    parser.add_argument("--dry-run", action="store_true", help="count, change nothing")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.org, arguments.dry_run))

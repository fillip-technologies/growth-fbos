"""
Customers that may be the same business as one about to be created (a lead being converted):
the same GSTIN, PAN or contact email, or a name that is the same once the legal suffixes
("Pvt Ltd", "LLP") are dropped. Suggestions only; nothing is refused for them.
"""

import re
import uuid
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.client import Client, ClientContact
from schemas.client import ClientMatch

LEGAL_WORDS = {"pvt", "private", "ltd", "limited", "llp", "inc", "co", "company", "corp", "corporation", "the", "and"}
MAX_MATCHES = 10
# Names shorter than this once cleaned ("AB") match too much to suggest anything.
MIN_NAME_LENGTH = 3


def name_key(name: str) -> str:
    words = re.findall(r"[a-z0-9]+", name.lower())
    return " ".join(w for w in words if w not in LEGAL_WORDS)


async def find_matches(
    session: AsyncSession,
    org_id: uuid.UUID,
    gstin: Optional[str] = None,
    pan: Optional[str] = None,
    email: Optional[str] = None,
    name: Optional[str] = None,
) -> list[ClientMatch]:
    reasons: dict[uuid.UUID, list[str]] = {}
    clients: dict[uuid.UUID, Client] = {}

    def found(client: Client, reason: str) -> None:
        clients[client.id] = client
        if reason not in reasons.setdefault(client.id, []):
            reasons[client.id].append(reason)

    in_org = select(Client).where(Client.organization_id == org_id)
    gstin, pan, email = (gstin or "").strip().upper(), (pan or "").strip().upper(), (email or "").strip().lower()
    if gstin:
        for client in (await session.execute(in_org.where(func.upper(Client.gstin) == gstin))).scalars():
            found(client, "gstin")
    # A GSTIN carries the PAN in characters 3-12.
    pans = {p for p in (pan, gstin[2:12] if len(gstin) == 15 else "") if p}
    if pans:
        for client in (await session.execute(in_org.where(func.upper(Client.pan).in_(pans)))).scalars():
            found(client, "pan")
    if email:
        rows = await session.execute(
            in_org.join(ClientContact, ClientContact.client_id == Client.id).where(func.lower(ClientContact.email) == email)
        )
        for client in rows.scalars():
            found(client, "email")
    key = name_key(name or "")
    if len(key) >= MIN_NAME_LENGTH:
        words = key.split()
        rows = await session.execute(in_org.where(or_(*(func.lower(Client.name).contains(w) for w in words[:3]))))
        for client in rows.scalars():
            other = name_key(client.name)
            if other and (other == key or (len(other) >= MIN_NAME_LENGTH and (other in key or key in other))):
                found(client, "name")

    # Strongest evidence first: a tax id beats an email beats a name.
    strength = {"gstin": 0, "pan": 1, "email": 2, "name": 3}
    ordered = sorted(clients.values(), key=lambda c: (min(strength[r] for r in reasons[c.id]), c.name.lower()))
    return [
        ClientMatch(id=c.id, code=c.code, name=c.name, status=c.status, gstin=c.gstin, reasons=reasons[c.id])
        for c in ordered[:MAX_MATCHES]
    ]

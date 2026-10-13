"""
Emailing a contract, with the files chosen from it, to the customer: for signing while it
waits for a signature, or as a copy once it is active. Sending it changes nothing on the
contract; the email goes on its timeline (and its opportunity's).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ContractNotEmailableError
from models.client import Client
from models.opportunity import Opportunity
from schemas.contract import ContractEmailSent
from schemas.customer_email import CustomerEmailCreate, CustomerEmailDraft
from services import customer_email
from services.contract_service import ContractService, get_contract_in_org, log_on_timeline
from services.documents_client import DocumentsClient, SubjectRef
from services.identity_client import Actor

EMAILABLE = ("draft", "pending_signature", "active", "completed")
AWAITING_SIGNATURE = ("draft", "pending_signature")


async def build_draft(session: AsyncSession, org_id: uuid.UUID, actor: Actor, contract_id: uuid.UUID) -> CustomerEmailDraft:
    contract = await get_contract_in_org(session, org_id, contract_id)
    client = await session.get(Client, contract.client_id)
    opportunity = await session.get(Opportunity, contract.opportunity_id) if contract.opportunity_id else None
    contacts = await customer_email.contacts(session, contract.client_id, opportunity)
    primary = customer_email.primary(contacts)

    about = f" for {opportunity.name}" if opportunity else ""
    if contract.status in AWAITING_SIGNATURE:
        body = (
            f"Please find attached our contract {contract.contract_no}{about}, "
            f"for a total of {customer_email.money(contract.total_value, contract.currency)}.\n\n"
            "Please sign it and send us the signed copy."
        )
    else:
        body = f"Please find attached a copy of our contract {contract.contract_no}{about}."
    message = f"{customer_email.greeting(primary)}\n\n{body}\n\nLet us know if you have any questions.\n\nRegards,\n{actor.name}"
    return CustomerEmailDraft(
        sender=await customer_email.sender(),
        contacts=contacts,
        to=[primary.email] if primary else [],
        subject=f"Contract {contract.contract_no}{about} - {client.name}",
        message=message,
        emailable=contract.status in EMAILABLE,
    )


async def send(
    session: AsyncSession,
    org_id: uuid.UUID,
    actor: Actor,
    documents: DocumentsClient,
    authorization: str,
    contract_id: uuid.UUID,
    data: CustomerEmailCreate,
) -> ContractEmailSent:
    """Sends, then logs it on the timeline. The caller commits only after this returns."""
    contract = await get_contract_in_org(session, org_id, contract_id)
    if contract.status not in EMAILABLE:
        raise ContractNotEmailableError(contract.status)

    attached, files = await customer_email.attachments(
        documents, authorization, org_id, SubjectRef("revenue.contract", contract_id), data.document_ids
    )
    sent = await customer_email.deliver(data, attached)
    await log_on_timeline(
        session, contract, actor.user_id,
        customer_email.summary(f"contract {contract.contract_no}", data, files), "emailed", activity_type="email",
    )

    return ContractEmailSent(
        from_address=sent["from_address"],
        from_name=sent["from_name"],
        to=data.to,
        cc=data.cc,
        bcc=data.bcc,
        subject=data.subject,
        attachments=files,
        contract=await ContractService.get_contract(session, contract_id, org_id),
    )

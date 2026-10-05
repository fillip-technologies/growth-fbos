"""
Who may see and change which documents.

Visibility follows the subject: a document linked to a contract is visible to whoever can
see that contract, and changing it (new version, new link, external share) needs the right
to attach documents to every record it is linked to, which is also how a closed record
(an accepted quotation) stops taking files. A document linked to nothing belongs to its
owner. Client administrators see every document of the organization, but a closed record
still refuses new files from them.
"""

from dataclasses import dataclass
import uuid

from exceptions import DocumentNotFoundError, DocumentsServiceError, PermissionDeniedError
from models.document import Document
from services.identity_client import Actor
from services.subject_client import SubjectAccess, SubjectAction, SubjectClient, is_access_denial

PERM_READ = "document.read"
PERM_UPLOAD = "document.upload"
PERM_SHARE = "document.share"
PERM_MANAGE_CATEGORIES = "document.category.manage"


@dataclass(frozen=True)
class Caller:
    """The signed-in user, plus what is needed to ask other services about them."""

    actor: Actor
    authorization: str
    subjects: SubjectClient

    @property
    def user_id(self) -> uuid.UUID:
        return self.actor.user_id

    @property
    def organization_id(self) -> uuid.UUID:
        return self.actor.organization_id

    def require(self, permission: str) -> None:
        if not self.actor.has(permission):
            raise PermissionDeniedError(permission)

    async def check_subject(self, subject_type: str, subject_id: uuid.UUID, action: SubjectAction) -> SubjectAccess:
        return await self.subjects.check(
            self.authorization, self.user_id, self.organization_id, subject_type, subject_id, action
        )


async def can_read_document(caller: Caller, doc: Document) -> bool:
    if caller.actor.is_superuser or doc.owner_user_id == caller.user_id:
        return True
    for link in doc.links:
        try:
            await caller.check_subject(link.subject_type, link.subject_id, "read")
        except DocumentsServiceError as error:
            if not is_access_denial(error):
                raise
            continue
        return True
    return False


async def require_document_read(caller: Caller, doc: Document) -> None:
    """Raises 404 (not 403) so the document's existence isn't revealed."""
    if not await can_read_document(caller, doc):
        raise DocumentNotFoundError(str(doc.id))


async def require_document_write(caller: Caller, doc: Document) -> None:
    """Every linked record must accept documents; an unlinked one is its owner's."""
    await require_document_read(caller, doc)
    if not doc.links:
        if caller.actor.is_superuser or doc.owner_user_id == caller.user_id:
            return
        raise DocumentNotFoundError(str(doc.id))
    for link in doc.links:
        await caller.check_subject(link.subject_type, link.subject_id, "attach")

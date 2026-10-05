import uuid

import httpx
import pytest

from exceptions import DocumentsServiceError, SubjectNotFoundError, SubjectServiceUnavailableError
from services.subject_client import SubjectClient

ORG = uuid.uuid4()
USER = uuid.uuid4()
SUBJECT = uuid.uuid4()


def client_answering(handler, cache_seconds: float = 30.0) -> tuple[SubjectClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    subjects = SubjectClient(http, {"revenue": "http://revenue/api/revenue/v1"}, "secret", cache_seconds)
    return subjects, seen


def allowed(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"organization_id": str(ORG), "label": "CTR-1"})


async def check(subjects: SubjectClient, action="read", subject_type="revenue.contract"):
    return await subjects.check("Bearer t", USER, ORG, subject_type, SUBJECT, action)


@pytest.mark.asyncio
async def test_asks_the_owning_service_with_the_callers_credentials():
    subjects, seen = client_answering(allowed)
    access = await check(subjects, "attach")
    assert access.label == "CTR-1"
    request = seen[0]
    assert request.url.path == f"/api/revenue/v1/internal/subject-access/revenue.contract/{SUBJECT}"
    assert request.url.params["action"] == "attach"
    assert request.headers["Authorization"] == "Bearer t"
    assert request.headers["X-Organization-Id"] == str(ORG)
    assert request.headers["X-FBOS-Internal-Token"] == "secret"


@pytest.mark.asyncio
async def test_unknown_service_prefix_is_not_attachable():
    subjects, seen = client_answering(allowed)
    with pytest.raises(SubjectNotFoundError):
        await check(subjects, subject_type="billing.invoice")
    assert seen == []


@pytest.mark.asyncio
async def test_record_of_another_organization_counts_as_missing():
    subjects, _ = client_answering(lambda r: httpx.Response(200, json={"organization_id": str(uuid.uuid4())}))
    with pytest.raises(SubjectNotFoundError):
        await check(subjects)


@pytest.mark.asyncio
async def test_owner_errors_are_relayed():
    subjects, _ = client_answering(
        lambda r: httpx.Response(409, json={"detail": {"code": "SUBJECT_LOCKED", "message": "Accepted"}})
    )
    with pytest.raises(DocumentsServiceError) as raised:
        await check(subjects, "attach")
    assert raised.value.status_code == 409
    assert raised.value.code == "SUBJECT_LOCKED"


@pytest.mark.asyncio
async def test_owner_down_is_a_503():
    def fail(request):
        raise httpx.ConnectError("down")

    subjects, _ = client_answering(fail)
    with pytest.raises(SubjectServiceUnavailableError):
        await check(subjects)


@pytest.mark.asyncio
async def test_reads_are_cached_but_attach_checks_never_are():
    subjects, seen = client_answering(allowed)
    await check(subjects, "read")
    await check(subjects, "read")
    assert len(seen) == 1
    await check(subjects, "attach")
    await check(subjects, "attach")
    assert len(seen) == 3

"""
Read-only aggregates management pulls from the services that own the data (plan §5.2: pull, not
push, so any window can simply be asked for again).

- People `GET /api/people/v1/internal/absences?organization_id&from&to`
  -> {"data": [{"user_id", "starts_on", "ends_on", "half_day": bool}]}  (approved absences only)
- Delivery `GET /api/delivery/v1/internal/effort?organization_id&from&to`
  -> {"data": [{"user_id", "day", "minutes", "billable": bool, "productive": bool}]}
- Revenue `GET /api/revenue/v1/internal/revenue-actuals?organization_id&from&to`
  -> {"data": [{"id", "doc_type", "occurred_on", "amount", "currency"}]}  (issued documents at their
  taxable value, credit notes negative; `id` never changes)

All three are read-only endpoints in the services that own the data. Until they exist (404), or when the service can't be
reached, the answer is None: "not known", which callers report as such instead of as zero.
"""

from dataclasses import dataclass
from datetime import date
import logging
from typing import Any, Optional
import uuid

import httpx

logger = logging.getLogger("management.sources")

ABSENCES_PATH = "/api/people/v1/internal/absences"
EFFORT_PATH = "/api/delivery/v1/internal/effort"
REVENUE_ACTUALS_PATH = "/api/revenue/v1/internal/revenue-actuals"


@dataclass(frozen=True)
class Absence:
    user_id: uuid.UUID
    starts_on: date
    ends_on: date
    half_day: bool = False


@dataclass(frozen=True)
class Effort:
    user_id: uuid.UUID
    day: date
    minutes: int
    billable: bool
    productive: bool


@dataclass(frozen=True)
class RevenueActual:
    id: uuid.UUID
    doc_type: str
    occurred_on: date
    amount: float
    currency: str


class SourceClient:
    def __init__(self, http: httpx.AsyncClient, internal_token: str, path: str, service: str) -> None:
        self._http = http
        self._internal_token = internal_token
        self._path = path
        self._service = service

    async def _rows(self, organization_id: uuid.UUID, from_date: date, to_date: date) -> Optional[list[dict[str, Any]]]:
        headers = {"X-FBOS-Internal-Token": self._internal_token} if self._internal_token else {}
        params = {"organization_id": str(organization_id), "from": from_date.isoformat(), "to": to_date.isoformat()}
        try:
            response = await self._http.get(self._path, headers=headers, params=params)
        except httpx.HTTPError as exc:
            logger.warning("%s unreachable for %s: %s", self._service, self._path, exc)
            return None
        if response.status_code >= 400:
            logger.info("%s answered %s for %s", self._service, response.status_code, self._path)
            return None
        try:
            rows = response.json().get("data")
        except ValueError:
            return None
        return rows if isinstance(rows, list) else None


class AbsenceClient(SourceClient):
    def __init__(self, http: httpx.AsyncClient, internal_token: str) -> None:
        super().__init__(http, internal_token, ABSENCES_PATH, "people")

    async def absences(self, organization_id: uuid.UUID, from_date: date, to_date: date) -> Optional[list[Absence]]:
        rows = await self._rows(organization_id, from_date, to_date)
        if rows is None:
            return None
        return [
            Absence(
                user_id=uuid.UUID(row["user_id"]),
                starts_on=date.fromisoformat(row["starts_on"]),
                ends_on=date.fromisoformat(row["ends_on"]),
                half_day=bool(row.get("half_day")),
            )
            for row in rows
        ]


class EffortClient(SourceClient):
    def __init__(self, http: httpx.AsyncClient, internal_token: str) -> None:
        super().__init__(http, internal_token, EFFORT_PATH, "delivery")

    async def effort(self, organization_id: uuid.UUID, from_date: date, to_date: date) -> Optional[list[Effort]]:
        rows = await self._rows(organization_id, from_date, to_date)
        if rows is None:
            return None
        return [
            Effort(
                user_id=uuid.UUID(row["user_id"]),
                day=date.fromisoformat(row["day"]),
                minutes=int(row["minutes"]),
                billable=bool(row.get("billable")),
                productive=bool(row.get("productive", row.get("billable"))),
            )
            for row in rows
        ]


class RevenueClient(SourceClient):
    def __init__(self, http: httpx.AsyncClient, internal_token: str) -> None:
        super().__init__(http, internal_token, REVENUE_ACTUALS_PATH, "revenue")

    async def revenue_actuals(self, organization_id: uuid.UUID, from_date: date, to_date: date) -> Optional[list[RevenueActual]]:
        rows = await self._rows(organization_id, from_date, to_date)
        if rows is None:
            return None
        return [
            RevenueActual(
                id=uuid.UUID(row["id"]),
                doc_type=str(row.get("doc_type") or "document"),
                occurred_on=date.fromisoformat(row["occurred_on"]),
                amount=float(row["amount"]),
                currency=str(row["currency"]).upper(),
            )
            for row in rows
        ]

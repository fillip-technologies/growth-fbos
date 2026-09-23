import asyncio

import httpx

from config import settings
from schemas.home import HomeSummary, TasksSummary


async def _get_json(client: httpx.AsyncClient, url: str, token: str) -> dict:
    response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    return response.json()


class AggregationService:
    """
    Fans out to Delivery, Control and Communication in parallel to build the home
    screen summary. A slow or failing dependency is dropped and reported in
    `degraded` instead of failing the whole request.
    """

    async def get_home_summary(self, token: str) -> HomeSummary:
        timeout = httpx.Timeout(settings.aggregation_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            results = await asyncio.gather(
                _get_json(client, f"{settings.delivery_service_url}/v1/tasks/summary", token),
                _get_json(client, f"{settings.control_service_url}/v1/approval-requests/summary", token),
                _get_json(client, f"{settings.communication_service_url}/v1/inbox/unread-count", token),
                return_exceptions=True,
            )

        tasks_result, approvals_result, notifications_result = results
        degraded: list[str] = []

        if isinstance(tasks_result, Exception):
            degraded.append("delivery")
            tasks = TasksSummary(assigned_open=0, due_today=0, overdue=0)
        else:
            tasks = TasksSummary(**tasks_result)

        if isinstance(approvals_result, Exception):
            degraded.append("control")
            approvals_pending = 0
            escalations_open = 0
        else:
            approvals_pending = approvals_result.get("approvals_pending", 0)
            escalations_open = approvals_result.get("escalations_open", 0)

        if isinstance(notifications_result, Exception):
            degraded.append("communication")
            unread_notifications = 0
        else:
            unread_notifications = notifications_result.get("count", 0)

        return HomeSummary(
            tasks=tasks,
            approvals_pending=approvals_pending,
            escalations_open=escalations_open,
            unread_notifications=unread_notifications,
            degraded=degraded,
        )


aggregation_service = AggregationService()

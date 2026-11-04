"""
The CEO Command Center's daily snapshots (CEO plan B4): which metrics the gateway's nightly job
writes to `metric_daily`, how a longer period adds them up, and who may read them.

Each snapshot is one company's figure for one day (`dimension_key` "global"):
- a flow is what happened that day (revenue invoiced, costs incurred). Payroll is a flow written
  once a month, on the 1st, because a payroll run belongs to a month, not a day. A longer period
  is the sum of its days.
- a stock is where things stood at the end of the day (money owed, people employed). A longer
  period takes its last day's value.

A company's day with no row means that figure could not be read that night: the number of days a
period has rows for is returned beside the value, so a gap is never shown as zero.
"""
from dataclasses import dataclass
from typing import Literal

Kind = Literal["flow", "stock"]


@dataclass(frozen=True)
class CeoMetric:
    kind: Kind
    financial: bool  # needs insight.ceo_dashboard.financials, as the matching card does


CEO_METRICS: dict[str, CeoMetric] = {
    # Revenue: invoiced net of tax, and what is owed and in the pipeline at the end of the day.
    "ceo.revenue": CeoMetric("flow", financial=False),
    "ceo.receivables": CeoMetric("stock", financial=False),
    "ceo.overdue": CeoMetric("stock", financial=False),
    "ceo.pipeline": CeoMetric("stock", financial=False),
    "ceo.clients": CeoMetric("stock", financial=False),
    # Delivery
    "ceo.active_work_units": CeoMetric("stock", financial=False),
    "ceo.at_risk_work_units": CeoMetric("stock", financial=False),
    "ceo.project_costs": CeoMetric("flow", financial=True),
    # People
    "ceo.headcount": CeoMetric("stock", financial=False),
    "ceo.payroll": CeoMetric("flow", financial=True),
    # Management: business health % (only on days a scorecard had results).
    "ceo.health_score": CeoMetric("stock", financial=False),
    # Assets, inventory (committed purchase orders) and finance.
    "ceo.asset_costs": CeoMetric("flow", financial=True),
    "ceo.procurement": CeoMetric("flow", financial=True),
    "ceo.operating_expenses": CeoMetric("flow", financial=True),
    "ceo.other_income": CeoMetric("flow", financial=True),
}

CEO_METRIC_PREFIX = "ceo."


def is_ceo_metric(metric_code: str) -> bool:
    return metric_code.startswith(CEO_METRIC_PREFIX)

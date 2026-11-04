"""
Management's permission codes, as identity's catalog names them (`management.<entity>.<action>`).

Routes are guarded with them (`require_permission`). Rules that depend on the record stay in the
service layer: a goal or initiative owner checks in on their own; a corrective action's owner
updates it; whoever holds a results/targets read only for their own records sees the ones scoped to
them (and those of goals they own). Approving a target or a budget is control's power (its approval
policies and approvers), so management has no `.approve` codes of its own.

Six reads are sensitive (identity's SENSITIVE_READ_CODES), so members don't get them by default:
BUDGET_READ, COST_READ, SCENARIO_READ, KPI_TARGET_READ, RESULT_READ, CAPACITY_READ.
"""

# Planning setup
FISCAL_YEAR_READ = "management.fiscal_year.read"
FISCAL_YEAR_MANAGE = "management.fiscal_year.manage"
PERIOD_READ = "management.period.read"
PERIOD_MANAGE = "management.period.manage"

# Goals and initiatives (initiatives cover milestones and the roadmap)
GOAL_READ = "management.goal.read"
GOAL_MANAGE = "management.goal.manage"
INITIATIVE_READ = "management.initiative.read"
INITIATIVE_MANAGE = "management.initiative.manage"
CHECK_IN_WRITE = "management.check_in.write"

# Budgets
BUDGET_READ = "management.budget.read"
BUDGET_MANAGE = "management.budget.manage"

# Scenarios
SCENARIO_READ = "management.scenario.read"
SCENARIO_MANAGE = "management.scenario.manage"

# KPIs
KPI_READ = "management.kpi.read"
KPI_MANAGE = "management.kpi.manage"
MEASUREMENT_CREATE = "management.measurement.create"
RESULT_READ = "management.result.read"
PERIOD_CLOSE_MANAGE = "management.period_close.manage"

# Targets
KPI_TARGET_READ = "management.kpi_target.read"
KPI_TARGET_MANAGE = "management.kpi_target.manage"

# Corrective actions
CORRECTIVE_ACTION_READ = "management.corrective_action.read"
CORRECTIVE_ACTION_MANAGE = "management.corrective_action.manage"

# Resources and capacity
RESOURCE_READ = "management.resource.read"
RESOURCE_MANAGE = "management.resource.manage"
SKILL_READ = "management.skill.read"
SKILL_MANAGE = "management.skill.manage"
CAPACITY_READ = "management.capacity.read"

# Demand and allocation
REQUIREMENT_MANAGE = "management.requirement.manage"
ALLOCATION_READ = "management.allocation.read"
ALLOCATION_MANAGE = "management.allocation.manage"
ALLOCATION_OVERRIDE = "management.allocation.override"

# Internal cost rates (effectively pay bands)
COST_READ = "management.cost.read"

# The business summary (CEO Command Center): business health from the scorecard, budget vs actual.
SUMMARY_READ = "management.summary.read"

ALL = frozenset(
    value for name, value in dict(globals()).items() if name.isupper() and isinstance(value, str)
)

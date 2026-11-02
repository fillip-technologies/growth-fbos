# Service 07 Management — plan

Status: **plan, not built.** Written 2026-11-02.

Management (`src/v1/07_management`, port 8007, `/api/management/v1`, database `fbos_management`) owns
three things: **planning** (fiscal years, goals, initiatives, budgets), **performance** (KPI targets,
measurements, results, corrective actions) and **resources and capacity** (who is available, who is
booked, where the gaps are).

All 30 tables are already modelled. Almost none of the behaviour exists. This plan says what the
module should be, how the large systems do it, and the order to build it in.

---

## 1. Where it stands today

Evidence, read 2026-11-02.

| Piece | State |
|---|---|
| Models | **30 tables, complete** — `models/planning.py` (12), `models/performance.py` (9), `models/resource.py` (9); matches `docs/schema/SCHEMA.md` "07_management — 30 tables" |
| Endpoints | **11**, all in one file (`routes/management.py`, 201 lines) |
| Tables with no endpoint | **18 of 30**: fiscal years, strategic goals, initiatives, milestones, roadmap items, scenarios, scenario values, budgets, budget lines, budget actuals, budget allocations, goal KPIs, KPI thresholds, KPI period snapshots, availability exceptions, resource requirements, allocation history, capacity gaps |
| Authentication | **Fake.** `dependencies.py:14-33` reads `X-FBOS-Org-Id` / `X-FBOS-User-Id` straight off the request and falls back to two hardcoded UUIDs. Anyone can act as anyone in any organization |
| Permissions | **None.** `grep -c "dependencies=" routes/management.py` → `0`. Identity's catalog holds **zero** `management.*` codes |
| `exceptions.py` | 238 lines, **21 exception classes, none imported anywhere** |
| Migrations | **None.** `migrations/versions/` holds only `.gitkeep`; tables appear from `Base.metadata.create_all` in `main.py:14` |
| Tests | **None.** No `tests/` directory |
| Service clients | **None.** No `identity_client.py`, no notification client, no worker |
| Frontend | **None.** No `features/management` in `clientadmin`, no `ACCESS` rules, no `/api/management` proxy in `vite.config.js` |
| Gateway | **Already wired** — `00_gateway/config.py:23` and `routes/proxy.py:17`; `docker-compose.yml:184` runs the service |

### The three functional holes

**1. There is no KPI engine.** `kpi_results` is only ever read. Nothing turns measurements into an
actual value, an achievement percentage or a RAG colour. `create_corrective_action`
(`services/management_service.py:344-352`) *fabricates* a result row with `actual_value=0`,
`target_value=0`, `status="amber"`, `inputs_hash=""` when none exists — an invented number that a
manager would read as real.

**2. There is no capacity ledger writer.** `capacity_ledger` is "daily precomputed" capacity, and
nothing precomputes it. So `GET /availability` returns zero minutes for everyone, `GET /capacity`
returns zero utilization, and `POST /allocations`' overload check (`:450-468`) cannot ever fire
because it loops over an empty table. The one safety rule in the module is inert.

**3. Approvals dead-end.** `kpi_targets.approval_request_id` and `budgets.approval_request_id` exist;
Control is never called. `submit_kpi_target` flips the status to `pending_approval` and **nothing in
the system can ever approve it** — the record is stuck forever.

Smaller defects: `UserRef(name="Owner")`, `name="Resource"`, `UnitRef(name="Unit")` are hardcoded
display names; `__import__('schemas.common', fromlist=['PageMeta'])` at `:133`; `from fastapi import
HTTPException` inside eight function bodies; `CapacityLedger.overload == True` at `:528`; nothing
writes `allocation_history`.

---

## 2. How the real systems do it

Management is not one product in the market — it is three, and each has its own established pattern.
Taking each from the right benchmark is cheaper than inventing one model for all three.

| FBOS module | Real-world category | Benchmarks read |
|---|---|---|
| Planning (goals, initiatives, budgets) | Strategy execution + FP&A | Balanced Scorecard, Cascade, ClearPoint; FP&A variance and rolling-forecast practice |
| Performance (KPIs) | Scorecard + semantic/metric layer | ClearPoint RAG playbook, Intrafocus KPI design; dbt MetricFlow / Cube semantic layer |
| Resources and capacity | PSA / resource management | Kantata, Float, Resource Guru; SPI Research utilization benchmarks |

Sources are secondary (vendor documentation, vendor blogs, one arXiv paper, Wikipedia). Treat product
detail with caution; the patterns below were corroborated across more than one source.

### 2.1 Resource management — soft and hard bookings

- A **soft booking** is a tentative assignment; a **hard booking** is a confirmed commitment that
  takes the person out of availability for the period.
- **Kantata** is the most explicit, and its three rules are the ones worth copying:
  1. Soft allocations render differently (striped) from hard ones.
  2. **Only a named resource can be hard-booked** — an unnamed role must be converted to a person first.
  3. **Both soft and hard count toward capacity**, and overallocation is computed *across all projects*,
     not per project.
- **Float** holds a role before a person is chosen with **placeholders**; **Resource Guru** blocks
  double-booking at creation time against each resource's own calendar, and offers a **waiting list**
  for an overbooked person instead of silently overloading them.

**This maps onto the existing tables with no schema change**: `resource_requirements` is the
placeholder (demand, with `skill_id` + `min_level` + `quantity` and no person), and `allocations` is
the booking, whose `status` already defaults to `"proposed"` — soft — with `"confirmed"` for hard.

### 2.2 Utilization — the denominator is the whole game

- Billable utilization = billable hours ÷ **available** hours. Available hours must be net of time
  off, holidays and planned leave; using a gross 40-hour week understates utilization.
- Three flavours are standard: **billable**, **productive** (billable plus internal work deemed
  strategic) and **total** (all recorded time).
- **Bench rate** = unassigned share of the team. One source suggests flagging anyone unassigned for
  about two weeks.
- The gaming failure mode, stated plainly by Wikipedia: *if a business stops recording non-billable
  time, its utilization rate will always be 100%*.
- Benchmarks: 65–85% depending on role; SPI Research's 2025 benchmark (403 firms) reports a 68.9%
  average for 2024, via a secondary source only.

**Consequence for FBOS**: utilization is denominated by **calendar capacity from the ledger**, never
by submitted timesheet totals. `Resource.daily_capacity_minutes` (default 480) is only the gross
fallback; the real number per day is capacity-from-calendar × FTE, minus availability exceptions.

### 2.3 KPI governance — owner, threshold, evidence, narrative

- A scorecard without named owners "becomes observational rather than actionable". Each KPI should
  carry an **owner, threshold, reporting frequency, escalation rule and evidence source**.
- A KPI without defined acceptable and unacceptable bounds is not meaningful. Amber is commonly
  placed at roughly 60–80% of the red threshold; thresholds should be written as numbers, and the
  colour then follows from them mechanically.
- **A colour alone misleads — narrative must accompany it.** A red item without an accountable owner
  and a due date is just a reporting label.

`kpi_definitions` already has owner and frequency; `kpi_thresholds` has green/amber; `kpi_sources` is
the evidence source. **Missing: the escalation rule, and the narrative.**

### 2.4 OKR check-ins — confidence is forward-looking, achievement is backward-looking

- Broadcom Rally models a **confidence score** as a manual 0.0–1.0 value on an objective, in three
  bands: **0.7–1.0** confident, **0.4–0.6** believable but at risk, **0.0–0.3** change approach.
- It is revisited on a cadence — weekly for short cycles, monthly for long ones.
- Sources are explicit that **confidence is not the achievement score**: one looks ahead, the other
  is the average of key-result scores at the end.

FBOS has `achievement_pct` (backward) and no forward view at all. This is the one place the plan adds
a table.

### 2.5 The semantic layer — how to not compute a wrong number

- **Non-additive and semi-additive measures**: a balance, a headcount or a rate must not be summed
  across time. dbt declares a `non_additive_dimension` per measure precisely for this. The patent
  literature states the trap: totals for a non-additive measure are only correct when the caller
  knows which measures are non-additive.
- **Re-aggregating a non-additive measure is wrong unless the inner grain matches.** In testing, where
  a month-grain measure is broken down by day, MetricFlow **refuses the request** and Cube returns
  first-of-month values. Refusing is the safer behaviour.
- **Define the metric once, in a governed place, as versioned code with explicit logic and lineage** —
  that is the whole point of a metric layer, and `kpi_definitions.formula` + `version_no` +
  `kpi_results.inputs_hash` + `calc_version` already is one.

### 2.6 FP&A — three baselines, and money that is promised but not yet spent

- Variance analysis compares actuals against a **predetermined measure**, and the three baselines
  answer different questions: **vs budget** = do earlier commitments still hold (accountability);
  **vs forecast** = was the latest view accurate (model quality); **vs last year** = the underlying trend.
- A **rolling forecast** is built on operational drivers, not line items, which is what makes it fast
  to update. But only about **9%** of organisations run fully automated driver-based models — so a
  full driver engine is not where effort belongs.
- Material variances should feed back into the forecast; budget-vs-actual is a forward-planning tool,
  not a post-mortem.
- **Commitments / encumbrance** — money promised but not yet spent — did not appear in the general
  FP&A sources; it is a public-sector and procurement pattern. FBOS has purchase orders (Fixly
  inventory) and confirmed allocations, so a *committed* column is computable without a new table.

---

## 3. What Management is, and is not

The hardest part of this module is not code, it is boundaries: four other services already own
neighbouring data, and duplicating any of it is how this module rots.

| Boundary | Management owns | The other service owns | Rule |
|---|---|---|---|
| **vs Insight (08)** | Metrics **someone is accountable for**: a KPI with an owner, a target, a threshold and a consequence | Audit trail and ad-hoc analytics, dashboards and reports over raw data | If nobody is accountable for the number, it belongs in Insight |
| **vs Delivery (03)** | Cross-project, forward-looking reservation of a person's time, and their **total** load | Tasks, task assignment, time entries, work units, task time limits | An allocation reserves time against a subject (project, initiative); it is **never** a task assignment. Follows Delivery decision #7 — don't duplicate a module that works |
| **vs People (10)** | `Resource`: the **capacity projection** of a person (FTE, daily minutes, effective dates, skills) | The employee, their shift, their leave, their pay | One person has one employee record in People and one effective-dated resource row in Management |
| **vs Revenue (02)** | A **mirror** of actuals against budget lines, idempotent on `source_event_id` | Invoices, payments, the money itself | Management is **not** the ledger of record (Phase 2's open question stands) |
| **vs Control (04)** | The subject being approved, and its `approval_request_id` | The approval policy, steps, decisions, delegations | Every approval in Management goes through Control. No second approval engine |

**Explicitly out of scope**: task assignment, payroll, the general ledger, a driver-based forecast
engine, a second SLA engine, and ad-hoc report building.

---

## 4. Design

### 4.1 Planning

```
fiscal_year ──┬── planning_period (nested: quarter → month → sprint)
              └── budget ── budget_line ──┬── budget_actual   (mirrored, idempotent)
                                          └── budget_allocation (to an initiative)

strategic_goal (cascades: parent_goal_id) ──┬── goal_kpi (weighted)
                                            ├── initiative ──┬── initiative_milestone
                                            │                └── roadmap_item
                                            └── goal_check_in  ← NEW (§4.3)
```

Rules to enforce (none exist today): a period must sit inside its fiscal year; sibling periods of the
same `period_type` under one parent must not overlap; closing a fiscal year closes its periods;
a goal's period must belong to the goal's organization; a cascaded goal cannot outlive its parent.

### 4.2 Performance — the KPI engine

```
kpi_definition (owner, unit, direction, aggregation, formula, frequency, version_no)
   ├── kpi_source      (how it is fed: manual | query | event)
   ├── kpi_threshold    (green_from_pct, amber_from_pct, per unit)
   ├── kpi_measurement  APPEND-ONLY ledger; a correction writes a reversal (reverses_id)
   └── kpi_target       (period × scope; revision_no; approved via Control)
                │
                ▼
           kpi_result   DERIVED CACHE, upserted on (kpi, period, scope_key)
                │        actual, target, achievement_pct, variance, RAG status, trend,
                │        calc_version, inputs_hash
                ├── kpi_period_snapshot   (frozen at period close — immutable)
                └── corrective_action     (owner + due date + optional Delivery task)
```

**The calculator** (new, `services/kpi_engine.py`):

1. Collect measurements for the KPI in the period, filtered to the scope, **net of reversals**.
2. Aggregate per `kpi_definitions.aggregation` — `sum | avg | last | min | max | count_distinct | ratio`.
3. **Refuse, do not guess**, when a non-additive aggregation is asked for over a dimension it cannot
   be summed across (dbt's behaviour, §2.5). Answer 422 `KPI_NOT_AGGREGABLE` rather than a wrong number.
4. Resolve the governing target: the latest approved `kpi_target` for that period and scope
   (`supersedes_id` chains revisions).
5. `achievement_pct` honours `direction` — `actual/target` for `higher_is_better`, `target/actual` for
   `lower_is_better`. A zero target is `null`, never a division by zero.
6. RAG from `kpi_thresholds` (unit-specific first, then the KPI default), thresholds as numbers so the
   colour is mechanical.
7. `trend` by comparing the previous period's result.
8. `inputs_hash` = hash over the contributing measurement ids and values, so a stale result is
   **detectable** and recomputation is idempotent.
9. A **closed** period refuses new measurements and recalculation; a restatement is a new
   `calc_version` with a new snapshot, never an edit of the frozen one. This is the same freeze rule
   Revenue uses for issued tax documents.

### 4.3 The one new table: `goal_check_ins`

Everything else fits the existing 30. This adds the forward-looking view the benchmarks all have and
FBOS has nowhere (§2.3, §2.4):

| Column | Why |
|---|---|
| `goal_id` / `initiative_id` (one of) | What is being checked in on |
| `period_id` | The cadence bucket |
| `confidence` NUMERIC(3,2) | 0.00–1.00, Rally's three bands; forward-looking |
| `rag` | The owner's own colour, which may disagree with the computed one — and that disagreement is the signal |
| `narrative` TEXT | "A colour alone misleads" |
| `author_user_id`, `created_at` | Accountability |

Append-only: a new check-in each week or month, never an edit. The scorecard shows computed
achievement next to the owner's stated confidence.

### 4.4 Resources and capacity

```
Identity /internal/work-calendars ─┐
Identity /internal/people/employees┤
People   /internal/absences  (new) ├──► capacity ledger builder (worker, idempotent)
Delivery /internal/effort    (new) ┤         │
Management allocations ────────────┘         ▼
                                 capacity_ledger (resource × day)
                                 capacity, allocated, actual, overload
```

Per resource × day: `capacity_minutes` = the unit's work calendar for that day × FTE, **minus**
overlapping `availability_exceptions`; `allocated_minutes` = sum of overlapping allocations'
`minutes_per_day` (soft **and** hard, per Kantata); `actual_minutes` from Delivery time entries;
`overload = allocated > capacity`.

The builder is **rebuildable for any window** and idempotent — rerunning it for a date range must
produce the same rows. That is what makes late leave approvals, backdated timesheets and corrected
calendars self-heal, and it is why the plan pulls rather than consumes events (§5.2).

**Demand and booking**, per §2.1:

| Concept | Table | Status flow |
|---|---|---|
| Demand / placeholder | `resource_requirements` | `open → partially_filled → filled → cancelled` |
| Soft booking | `allocations` | `proposed` |
| Hard booking | `allocations` | `confirmed` — requires a named resource |
| Change log | `allocation_history` | every transition, with before/after and who |

Overload answers 409 `CAPACITY_EXCEEDED` listing the overload days. An override needs a reason, and
the reason plus the overrider go into `allocation_history` — Resource Guru blocks by default, and an
override that nobody can audit is the same as no block at all.

**Derived reads**: utilization (billable / productive / total, denominated by ledger capacity);
bench list (no confirmed allocation for ≥ 10 working days); `capacity_gaps` = demand by skill × unit ×
period minus available, with a severity.

---

## 5. Cross-service contracts

### 5.1 Permission codes

**29 new codes** for Identity's `PERMISSION_CATALOG`, shipped in the same change as the routes:

| Area | Codes |
|---|---|
| Planning setup | `management.fiscal_year.read`, `.manage`, `management.period.read`, `.manage` |
| Goals | `management.goal.read`, `.manage`, `management.initiative.read`, `.manage`, `management.check_in.write` |
| Budgets | `management.budget.read`, `.manage`, `.approve` |
| Scenarios | `management.scenario.read`, `.manage` |
| KPIs | `management.kpi.read`, `.manage`, `management.measurement.create`, `management.result.read`, `management.period_close.manage` |
| Targets | `management.kpi_target.read`, `.manage`, `.approve` |
| Corrective actions | `management.corrective_action.read`, `.manage` |
| Resources | `management.resource.read`, `.manage`, `management.skill.read`, `.manage`, `management.capacity.read` |
| Allocation | `management.requirement.manage`, `management.allocation.read`, `.manage`, `.override` |
| Cost | `management.cost.read` |

**Six of these must go into `SENSITIVE_READ_CODES` in the same commit.** Identity auto-grants every
new `.read` code to every `member` preset (`permission_catalog.py:186-191`), so shipping them without
this hands the whole company the company's budget:

| Code | Why it must not reach every member |
|---|---|
| `management.budget.read` | Every budget and every line, company-wide |
| `management.cost.read` | Internal cost rates — effectively pay bands |
| `management.scenario.read` | Unannounced plans (headcount cuts model as a scenario) |
| `management.kpi_target.read` | Targets scoped to one person are individual performance data |
| `management.result.read` | Likewise for achievement against them |
| `management.capacity.read` | Everyone's workload and bench status |

**Record-level rules** sit in the service layer on top of the codes (per `AGENT_PERMISSIONS.md`):
a person with `own_records_only` on `management.result.read` sees targets and results where
`scope_user_id` is themselves; a goal owner sees their own goals' results regardless.

### 5.2 Service-to-service: pull, not push

FBOS has **no event bus**. Each service has its own outbox table and a worker that posts to one
destination's `/internal/*` endpoint (`03_delivery/models/outbox.py`). Two options for feeding
Management:

| Option | Verdict |
|---|---|
| **Push** — every source service writes `destination: "management"` outbox rows | **No.** Each new KPI needs a change in a service that does not care about KPIs; events cannot be replayed for a backfill; and Phase 5 already shows how this rots — People writes onboarding events for Identity and Assets and *"nothing consumes those events yet"* |
| **Pull** — Management's worker asks each source for aggregates over a date range | **Chosen.** KPIs are periodic aggregates, not real-time events. Backfill, restatement and late-arriving data are then just "ask again for that window", and the blast radius of a new KPI stays inside Management plus one read endpoint |

| What Management needs | Endpoint | Exists? |
|---|---|---|
| Who is calling, and their codes | Identity `/internal/authz/actor` | **Yes** |
| Employees to create resources from | Identity `/internal/people/employees` | **Yes** |
| Working time per unit | Identity `/internal/work-calendars` | **Yes** |
| Whom to escalate a red KPI to | Identity `/internal/unit-heads` | **Yes** |
| Approved absences in a window | People `/internal/absences` | **New (People)** |
| Effort by user, day, billable flag | Delivery `/internal/effort` | **New (Delivery)** |
| Revenue actuals in a window | Revenue `/internal/revenue-actuals` | **New (Revenue)** |
| Raise an approval | Control `POST /requests` | **Yes** — new policies for `subject_type` `management.kpi_target` and `management.budget` |
| Notify an owner | Communication `/internal/notifications` | **Yes** — fire-and-forget, as People does |

Each new `/internal/*` endpoint is read-only, guarded by `verify_internal_caller`, and goes in **its
own** service's PR, deployed before the Management phase that needs it.

---

## 6. Build order

Convention from the house: backend PR merged and deployed first, checked on the live server, then the
frontend PR. Migrations additive. Anything that changes how numbers are produced is behind a
per-organization setting, off by default.

| Phase | Scope | Why here |
|---|---|---|
| **0 — Make it honest** | Replace the fake `dependencies.py` with the Identity-backed one (copy `10_people/dependencies.py`: `get_actor`, `require_permission`, `require_any_permission`, `verify_internal_caller`); add `services/identity_client.py` and wire it into `main.py`'s lifespan; add `permissions.py`; add the 29 codes **and** the 6 sensitive entries to Identity; guard all 11 existing routes; add `tests/` with a conftest, an auth test and the **no-unguarded-route** test (model: `04_control/tests/test_permissions.py`); baseline alembic migration; make the service layer use the 21 already-written exceptions, hoist the function-local imports, drop the `__import__` hack, `is_(True)`. **No new features.** | The service is currently an open door with a hardcoded org id. Nothing else may ship first |
| **A — Planning foundation** | Fiscal years, planning periods (nesting + overlap validation), goals (cascade, version), initiatives, milestones, roadmap items. 6 of the 18 orphan tables | Everything downstream is keyed on a period |
| **B — KPI engine** | Definitions CRUD + versioning, sources, thresholds; the measurement ledger (append-only, reversals, list); `services/kpi_engine.py` (§4.2); scorecard read; period close and snapshot freeze; corrective actions stop fabricating results | The module's reason to exist. Phase B is where "Performance" becomes real |
| **C — Check-ins** | `goal_check_ins` (§4.3) and the migration; confidence and narrative on the scorecard | Cheap, and it is the gap against every benchmark |
| **D — Budgets** | Budgets, lines, allocations; revisions; approval through Control; `/internal/budget-actuals` idempotent on `source_event_id`; the nightly Revenue pull; budget-vs-actual-vs-committed variance (§2.6) | Needs A (fiscal year) and Control policies |
| **E — Resources and the ledger** | Resources CRUD, effective-dated, with a **create-from-users** batch (mirror People's "Add from users"); skills; availability exceptions; **the capacity ledger builder** behind `CAPACITY_WORKER_ENABLED`, one server only | Without the ledger, availability, capacity and the overload check are all zeros today |
| **F — Demand and allocation** | Requirements as placeholders; soft → hard booking with Kantata's named-resource rule; overload 409 with override reason written to `allocation_history`; capacity gaps; utilization (3 flavours) and the bench list | Needs E. This is the half-built part finished |
| **G — Scenarios** | Copy a period's targets as a baseline, apply one assumption, compare. Deliberately small | Only ~9% of firms automate driver models; a what-if table is the right size |
| **H — Frontend (clientadmin)** | Scorecard, KPI setup, My targets, Goals & initiatives, Roadmap, Budgets, Variance, Resource planner (timeline with striped soft bookings), Availability, Capacity & bench, Corrective actions. Plus `ACCESS` rules, nav entries, and a `/api/management` proxy + `MANAGEMENT_URL` in `vite.config.js` | A console page per phase, after that phase is live |

Phases A–C and E–F are each independently shippable and each closes a group of the 18 orphan tables.

---

## 7. Decisions

| # | Decision | Why |
|---|---|---|
| 1 | Phase 0 ships before any feature | `dependencies.py` trusts caller-supplied ids and defaults to a hardcoded organization. Every number the module later produces is worthless if anyone can write it |
| 2 | Management pulls aggregates; it does not consume events | Backfill and restatement are first-class needs for a metric; People's unconsumed onboarding outbox is the warning |
| 3 | `capacity_ledger` is a rebuildable cache, never a source of truth | Any window can be recomputed, so late leave, backdated timesheets and corrected calendars self-heal |
| 4 | Both soft and hard allocations consume capacity; only a named resource can be hard-booked | Kantata; a soft booking that costs nothing is not a plan |
| 5 | Utilization is denominated by ledger capacity, never by submitted time | Otherwise the number is 100% for anyone who stops logging non-billable work |
| 6 | A non-additive aggregation over a dimension it cannot cross answers 422, not a number | MetricFlow refuses where Cube guesses; a silently wrong KPI is worse than a missing one |
| 7 | `kpi_results` is derived and keyed by `inputs_hash`; closed periods freeze into snapshots; restatements get a new `calc_version` | Same freeze rule as Revenue's issued documents. A number a manager was shown must stay reproducible |
| 8 | Every approval goes through Control | The engine, policies and delegations already exist there; `approval_request_id` is already the hook |
| 9 | An allocation is a time reservation, never a task assignment | Delivery owns tasks (its decision #7); two assignment systems would fight |
| 10 | `Resource.internal_cost_rate` is a rate-card figure set in Management, never synced from payroll | Syncing salary in would leak pay to everyone holding `management.resource.read` |
| 11 | `budget_actuals` is an idempotent mirror; Management is not the ledger of record | Phase 2 left "is FBOS the ledger of record" open; this does not pre-empt it |
| 12 | Owner-stated confidence is stored alongside computed achievement, and may disagree | The disagreement is the signal; one is forward-looking, the other backward |
| 13 | No driver-based forecast engine | ~9% of organisations automate one; `scenarios` + `scenario_values` is the right size |
| 14 | Six new `.read` codes are sensitive from the first commit | Identity auto-grants new `.read` codes to every member preset |

## 8. Open questions for the owner

1. **Scorecard or OKRs?** `strategic_goals` + `goal_kpis` + `kpi_targets` is a Balanced Scorecard.
   Check-ins with confidence (Phase C) make it OKR-shaped. Which vocabulary do the consoles use?
2. **Who sets a target?** Owner proposes and a manager approves through Control, or a planning team
   sets all of them centrally? It decides whether `management.kpi_target.manage` is broad or narrow.
3. **Does a person see their own numbers?** If yes, `management.result.read` ships with an
   "own records only" grant for everyone, and the scorecard needs a "my targets" page in Phase B, not H.
4. **Is capacity planned in days, or in minutes?** The tables are minutes. Most planners think in
   days or FTE-weeks. A display setting, or a different unit on the API?
5. **Budget currency.** `budgets.currency` defaults to `USD` while Revenue is India-first (GST, TDS).
   Should it default from `finance_settings`?
6. **Where do cost actuals come from** for a budget — payroll (People), purchases (Fixly inventory),
   or manual entry only in the first cut?
7. **Fiscal year.** Identity already stores `fiscal_year_start` per organization. Should Management's
   `fiscal_years` be generated from it rather than entered by hand?

## 9. Deploy notes

- **Deploy Identity first** — 29 new permission codes, and `SENSITIVE_READ_CODES` must contain the six
  before any member signs in.
- The remote `fbos_management` database already carries the 30 tables (created by `create_all`), so the
  **baseline migration must be stamped, not run** against it. Per Phase 0's standing rule: never run
  migrations against the shared remote databases from a dev machine.
- `CAPACITY_WORKER_ENABLED` on **one** server only (same rule as People's `ROLE_CHANGE_WORKER_ENABLED`).
- Control needs approval policies for `subject_type` `management.kpi_target` and `management.budget`
  before Phase B's submit and Phase D's budget approval do anything.
- Add `pytest`, `pytest-asyncio` and `aiosqlite` to `07_management/requirements.txt` — they are missing,
  which is why there are no tests.
- `vite.config.js` needs `MANAGEMENT_URL` and an `/api/management` proxy before Phase H.

---

## Appendix — sources

Resource management and utilization
- <https://knowledge.kantata.com/hc/en-us/articles/115004722914-Managing-Allocations-in-Resourcing>
- <https://www.saviom.com/blog/7-key-steps-for-soft-booking-resources-for-a-project/>
- <https://community.broadcom.com/viewthread?MID=823543>
- <https://www.kantata.com/blog/article/professional-services-utilization-benchmarks>
- <https://en.wikipedia.org/wiki/Utilization_rate>
- <https://www.ruddr.com/post/the-critical-importance-of-utilization-tracking-for-professional-services-firms>
- <https://www.saibon.io/blog/consultant-utilization-rate-benchmark>
- <https://productive.io/blog/capacity-planning-software/>

KPI governance and OKRs
- <https://www.clearpointstrategy.com/blog/establish-rag-statuses-for-kpis>
- <https://www.intrafocus.com/wp-content/uploads/2014/09/Developing-Meaningful-Key-Performance-Indicators-V7.pdf>
- <https://www.goelate.com/resource/company-scorecard>
- <https://techdocs.broadcom.com/us/en/ca-enterprise-software/valueops/rally/rally-help/planning/objectives-and-key-results-okrs/creating-okrs/enter-a-confidence-score.html>
- <https://en.wikipedia.org/wiki/Objectives_and_key_results>

Semantic layer
- <https://docs.getdbt.com/docs/build/measures>
- <https://motley.ai/compare/cube-vs-dbt-semantic-layer/>
- <https://arxiv.org/pdf/2604.15108>

FP&A
- <https://www.wallstreetprep.com/knowledge/budget-actual-variance-analysis-fpa/>
- <https://www.farseer.com/blog/rolling-forecast/>
- <https://bprglobal.co/resources/financial-planning-analysis/variance-analysis-guide/>
- <https://corporatefinanceinstitute.com/resources/fpa/types-of-variances-fpa>

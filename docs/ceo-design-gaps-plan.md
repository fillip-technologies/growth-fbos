# CEO Command Center — Design Gaps Plan

Status: **Phases 1–3 built, except item 9** (needs a migration) **and item 14** (Phase 4). Backend only, not
yet committed or deployed; the frontend still has to show the new fields. Written 2026-11-11, updated
2026-11-12.

The CEO Command Center design asks for 14 things the backend didn't give. This plan says where each
one's data lives, what had to change, and in what order. It extends
[`ceo-command-center-plan.md`](ceo-command-center-plan.md).

File references are relative to `fbos_services/src/v1/` unless stated otherwise; Fixly paths start
with `fixly/`.

## Where each item stands

| # | Item | Status | Database change |
|---|---|---|---|
| 1–4 | Previous period on state, product line, AMC revenue, income by type | **Built** | none |
| 5 | Procurement on / over budget | **Built** (D1 a) | none; needs a `procurement` budget line entered |
| 6 | Projects by state | **Built** | none |
| 7 | Hardware units sold | **Built** | none |
| 8 | Top products | **Built** | none |
| 9 | AMC by type | **Not built** | `offerings.amc_type` (Revenue, Alembic) |
| 10 | Field activity today | **Built** (D2 b) | none |
| 11 | Freelancer details | **Built** (D4 c, else b) | none |
| 12 | Business segments | **Built** (D5) | none |
| 13 | Investment in companies | **Built** | none |
| 14 | AI recommendations and chat | Not built (Phase 4, needs D6) | — |

---

## How the screen is built

`GET /api/bff/v1/screens/ceo` (gateway) reads one summary per service and company, in parallel
(`00_gateway/services/ceo_sources.py`), then a **second round** of lookups that join two services
(`00_gateway/services/ceo_follow_ups.py`, new), and adds it all up (`00_gateway/services/ceo_screen.py`)
into `00_gateway/schemas/ceo.py`. The nightly snapshots are read beside both rounds, so the second
round adds one round trip only to the live reads.

| Service | Summary endpoint | Built in | Permission |
|---|---|---|---|
| Revenue | `/api/revenue/v1/summaries/revenue` | `02_revenue/services/business_summary.py` | `revenue.summary.read` |
| Delivery | `/api/delivery/v1/summaries/delivery` | `03_delivery/services/business_summary.py` | `delivery.summary.read` |
| People | `/api/people/v1/summaries/people` | `10_people/services/business_summary.py` | `people.summary.read` |
| Management | `/api/management/v1/summaries/health` | `07_management/services/business_summary.py` | `management.summary.read` |
| Finance | `/api/finance/v1/summaries/finance` | `11_finance/services/business_summary.py` | `finance.summary.read` |
| Inventory (Fixly) | `/api/inventory/v1/reports/summary` | `fixly/fixly_backend/src/modules/inventory/routes/reports.js` | `inventory.report.read` |

The second round uses three new internal lookups, each behind the internal service token
(`X-FBOS-Internal-Token`, like the other `/internal` routes). Each is a `POST` because the list of ids
can be too long for a URL; none of them writes anything.

| Lookup | Asked for a company only when | Answers |
|---|---|---|
| Revenue `POST /api/revenue/v1/internal/clients/states` `{organization_id, client_ids}` | the caller read its Delivery **and** Revenue summaries | `{states: {client_id: state_code \| null}}`; ids that aren't the company's customers are left out |
| Delivery `POST /api/delivery/v1/internal/users/workload` `{organization_id, user_ids}` | the caller read its People **and** Delivery summaries | `{working_user_ids, running_projects}` |
| People `POST /api/people/v1/internal/workers/presence` `{organization_id, user_ids}` | the inventory read answered, and the caller read the inventory company's People summary | `{as_of, workers, unknown, on_leave, working: {office, field, remote, not_said}}` |

So a lookup never shows the caller anything their own summary permissions wouldn't. A refused
internal call (a wrong token) shows as `unavailable`, not `no_access`. Each list is capped at 2000
ids.

**No new permission codes.** Money stays behind `insight.ceo_dashboard.financials`. Every new card
says why it is empty (`no_access` / `unavailable` / `not_set_up`) instead of showing zero. All
response changes are **additive** (new optional fields), so today's frontend keeps working.

---

## Decisions

The recommended options were taken. Change them here before the frontend is built.

| # | Question | Taken |
|---|---|---|
| D1 | Procurement budget (item 5) | **(a)** Management's budget lines of category `procurement`, compared with Fixly's committed purchase orders. No budget link on purchase orders. |
| D2 | "Escalated" field visit (item 10) | **(b)** A visit still `scheduled` after its scheduled time. A visit `in_progress` past its time is not escalated, because the technician has started it. |
| D3 | AMC type (item 9) | Not built: both options need a migration. |
| D4 | Freelancer category (item 11) | **(c), else (b)**: the job family of the freelancer's primary position, otherwise their designation. No new `skill_category`. |
| D5 | Segment order (item 12) | As recommended, per invoice line: associate → AMC hardware → AMC services → hardware sales → government India / international → private India / international → other. |
| D6 | AI (item 14) | Open. |

---

## Phase 1 — Previous period on existing figures (items 1–4) · built

- **Revenue:** `revenue_by_state[]` and `revenue_by_product_line[]` gain `previous`; `amc` gains
  `revenue_previous`. A key that only the previous period has still shows (amount 0).
- **Finance:** `income_by_type[]` gains `previous`, under the same rule.
- **Gateway:** `Bucket.previous` and `AmcCard.revenue_previous`. `merge_buckets` adds up `previous`
  across companies. It stays `None` (not 0) when a source doesn't give it yet, so an older service
  still reads correctly.

## Phase 2 — New figures from stored data (items 6, 7, 8, 13) · built

| Item | Service returns | Screen field |
|---|---|---|
| 7 Hardware units | Revenue `hardware_units: {amount, previous}`: quantity on issued invoice lines whose offering's `product_line` is `hardware`, net of credit notes (AMC lines included) | `revenue.hardware_units` |
| 8 Top products | Revenue `top_products: [{offering_id, name, units, revenue}]`, top 10 by revenue | `revenue.top_products`: the same name across companies is one row; `revenue` only with financials, units always |
| 13 Investment in companies | Finance `income_by_type` key `investment_in_companies`: income on investments that have `investee_organization_id`, moved out of its own type (dividend, interest…) so it is not counted twice | `finance.income_by_type` |
| 6 Projects by state | Delivery `running_by_client: [{client_id, count}]`, plus Revenue's client-states lookup | `revenue.projects_by_state: {available, reason, rows: [{key, count}]}`; no customer, or a customer without a state, counts under `none` |

## Phase 3 — Items that needed a decision (5, 10, 11, 12) · built; item 9 not built

**5 Procurement against budget (D1 a).** Budgets are per fiscal year, so Management's summary
(`budget.procurement_approved`, `budget.procurement_for_period`) shares the year's approved
`procurement` lines evenly over the period's days inside that year. The gateway compares that with
the purchase orders committed in the period, for the company the inventory service serves:
`procurement.budget: {available, reason, budget, committed, used_pct, over_budget}` (financials
only). It shows `not_set_up` when the year has no `procurement` line.

This differs from the first draft: the draft had `on_budget_pct` / `over_budget_pct`, but those need a
budget on each purchase order (D1 b, a migration). Aggregate use and the amount over budget are what
the stored data can support.

**10 Field activity today (D2 b).** Fixly's summary adds `visits_today: {completed, in_progress,
pending, escalated}`: today's visits by `scheduled_at` in the server's own time zone, without
cancelled ones. It also adds `technicians.fbos_user_ids` and `technicians.unlinked` (technicians with
no FBOS user). The gateway asks People's presence lookup for those users and shows
`field.technicians_today: {at_office, in_field, remote, not_said, on_leave, not_marked, unlinked}`.
`unlinked` adds Fixly's unlinked technicians and the users People has no worker for, so the gap is
visible.

**11 Freelancer details (D4 c / b).** People's summary adds `freelancer_details: [{user_id,
category}]`. The gateway asks Delivery's workload lookup for those with a login and shows
`people.freelancer_details: {total, active, without_login, projects, top_categories}`. Here `active`
means an open task, or a place on a running project (manager, or a member whose staffing covers
today).

**12 Business segments (D5).** Revenue labels each issued invoice line with its segment
(`business_segment()` in `02_revenue/services/business_summary.py`) and returns
`revenue_by_business_segment`, plus `business_segments_by_work_unit` for invoices that name a project.
The gateway moves the lines of projects given to an associate into `associate`, using Delivery's
`partners[].work_unit_ids`, which it already reads. This differs from the first draft: Revenue makes no
call to Delivery, and **no migration was needed**. Today's `by_segment` is unchanged. Shown as
`revenue.by_business_segment`.

**9 AMC by type: not built.** Either D3 option needs a new column. The recommended one is
`offerings.amc_type VARCHAR(30) NULL` in Revenue (Alembic), with values `cctv`, `it_infrastructure`,
`software_website`, `field_equipment`, `other`. Then the offering create/update accepts it, the summary
returns `amc.by_type: [{key, count}]`, and the offering form gets the field.

## Phase 4 — AI recommendations and chat (item 14)

Not built. It needs D6 first, then its own plan: which model and provider, where the service runs,
cost limits, what is logged, and that answers only use figures the asker may already see (the same
permissions as the screen).

---

## Files changed

| Where | Files |
|---|---|
| Gateway | `schemas/ceo.py`, `services/ceo_sources.py`, `services/ceo_service.py`, `services/ceo_screen.py`, `services/ceo_follow_ups.py` (new); tests `test_ceo_screen.py`, `test_ceo_follow_ups.py` (new) |
| Revenue | `schemas/business_summary.py`, `services/business_summary.py`, `routes/summaries.py`; tests `test_summaries.py`, `test_internal_summary.py` |
| Delivery | `schemas/business_summary.py`, `services/business_summary.py`, `routes/summaries.py`; tests `test_business_summary.py` |
| People | `schemas/business_summary.py`, `services/business_summary.py`, `routes/summaries.py`; tests `test_business_summary.py`, `test_persistence.py` (presence lookup listed as read-only) |
| Management | `schemas/business_summary.py`, `services/business_summary.py`; tests `test_business_summary.py` |
| Finance | `schemas/business_summary.py`, `services/business_summary.py`; tests `test_business_summary.py` |
| Fixly | `src/modules/inventory/routes/reports.js`; tests `scripts/inventory_reports.test.mjs` |

## Verification done (2026-11-12)

Each service's full suite, offline in its container (`--network none`):

| Service | Result |
|---|---|
| Gateway | 54 passed |
| Revenue | 245 passed |
| Delivery | 227 passed |
| People | 179 passed |
| Management | 131 passed |
| Finance | 61 passed |
| Fixly `npm run test:unit` | 27 passed, 46 skipped (need a database), 2 failed in `scripts/push.test.mjs`. Those 2 fail the same way without this change. |

No migration was run and no database was touched.

## Still to do

1. Review and commit: one backend PR for `fbos_services`, one for Fixly. They can ship in either order,
   because the gateway treats missing new fields as "not given yet".
2. Deploy, then call `/api/bff/v1/screens/ceo` on the live server with and without `financials`.
3. Enter a `procurement` budget line per company in Management, so item 5 shows figures.
4. Frontend: show the new fields (above), with each card's `reason` when it is empty.
5. Item 9 (migration) when approved; Phase 4 after D6.

## Risks

- **Shared database:** dev and live share the Hostinger databases. Nothing here migrates. Item 9's
  migration will be additive and nullable.
- **Screen speed:** the summaries gained a few GROUP BY queries on existing indexes, and the second
  round adds one round trip (up to three lookups in parallel), still bounded by `CEO_TIMEOUT_SECONDS`
  per call.
- **Snapshots:** the nightly snapshots (`ceo_snapshots.py`) don't cover the new figures. Their previous
  period comes from live queries.
- **Time zone:** "today" for field visits is the inventory server's day, and for attendance it is the
  People server's day. Both should run in the business's time zone.

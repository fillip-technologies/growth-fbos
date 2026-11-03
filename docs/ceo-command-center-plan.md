# CEO Command Center & Unlimited Operator Client — Plan

Status: **Approved** · Written 2026-11-03 · Approved 2026-11-03

This plan covers two things:

- **Part A:** Fillip, the operator company that runs FBOS, gets no subscription window and no limits.
- **Part B:** a "Layer 1 – CEO Command Center" dashboard that rolls up every Fillip company,
  segment, associate and function on one screen.

Everything below was checked against the current code. File references are relative to
`fbos_services/src/v1/` unless stated otherwise.

---

## Decisions

| # | Question | Decision |
|---|---|---|
| 1 | How to model associate companies | Each associate is an **Organization under the Fillip client**, marked `relationship = associate`. Work Fillip gives to an associate is a **delivery work unit tagged with that associate's organization**, and what Fillip pays them is a **`cost_entries` row with category `subcontract`**. No new module is needed. |
| 2 | Where procurement lives | **Fixly.** `fixly_backend` already has Vendor → PurchaseOrder → GoodsReceipt, plus repairs, technicians and stock (`/api/inventory/v1`), and it accepts FBOS Identity tokens. The dashboard **reads** procurement from Fixly; FBOS does not build its own. |
| 3 | Order of work | Approved 2026-11-03. Part A first, then B1 → B4. Decision Matrix and Ask FBOS AI are **future scope** (not now). |
| 4 | Where non-hardware expenses and investments live | A **new `11_finance` service** (B3). Fixly stays hardware procurement only. |
| 5 | Business Health % formula | **Weighted status of the Management scorecard KPIs** (see B1.2 "Business Health"). |
| 6 | Who sees the Command Center | **Nobody by default except the system administrator, who grants access.** There is no hardcoded CEO-only rule. The administrator grants the permissions (B1.4) to any role or person in the Access editor, including whether they see sensitive figures. |

### Why decision 1 works this way
- Because of Part A, an associate's organization costs nothing in seats or orgs.
- An associate that uses FBOS gets its own revenue, projects and clients automatically. Widget 3's
  "Associate Companies (Total)" row is just the sum over organizations with `relationship = associate`.
- "Work given" and "Margin" (widget 4) come from data Fillip already records: the work unit's
  revenue (invoices with `work_unit_id`) minus its `subcontract` cost entries
  (`03_delivery/models/financial.py: CostEntry`).
- An associate that never signs in still works. It is an organization with no users, and Fillip's
  own records point at it.

---

## Part A — Fillip unlimited (no subscription)

### Current state
- `01_identity/models/client.py`: `max_organizations` (default 2), `max_users_per_org`
  (default 50), and `subscription_start`/`subscription_end` are all `NOT NULL`.
- `01_identity/services/subscription.py`: `is_client_usable()` blocks every user outside the window.
  It is enforced in `auth_service.py` (login, refresh, MFA) and in `dependencies.py`.
- The quota checks already treat `None` as unlimited:
  `services/organization_service.py:188` and `services/user_service.py:308`.

### Change
`NULL` means unlimited. No new "plan" table and no hardcoded client code.

| Step | File | Change |
|---|---|---|
| A1 | new Alembic migration in `01_identity/migrations/versions/` | Make `max_organizations`, `max_users_per_org` and `subscription_end` nullable. |
| A2 | `models/client.py` | Change the types to `Optional[...]`. |
| A3 | `services/subscription.py` | If `subscription_end is None`, `subscription_state()` returns `"unlimited"` and `is_client_usable()` returns true while `status == "active"`. |
| A4 | `schemas/client.py` | Create/update accept an explicit `null` for the three fields. The response allows `None` and the `"unlimited"` state. Defaults (2 / 50 / one year) still apply when a field is **omitted**. |
| A5 | `services/client_service.py:71-85, 125, 274-282` | Handle `None`: skip the `end < start` check, and send no end date in the welcome email. |
| A6 | `services/email_service.py:109` | Print "No expiry" when there is no end date. |
| A7 | Data | Set the Fillip client row to `NULL / NULL / NULL`, through the superadmin UI after A8 or a one-off script. |
| A8 | `fbos_frontend/superadmin` (`ClientCreate`, `ClientDetail`, `ClientsList`) | Add an "Unlimited (internal)" toggle that clears and disables the three inputs. The list shows an "Unlimited" badge. |
| A9 | `fbos_frontend/clientadmin` (`features/dashboard/components/SubscriptionOverview.jsx`, `features/dashboard/api.js`) | Show "Unlimited · No expiry" instead of quotas and a countdown. |

**Blast radius:** only Identity and two frontends. No other service reads subscription fields
(checked with grep).

**Tests:** subscription state with no end date; login works with no end date; org and user
creation with `None` limits; schema accepts `null`. Run `pytest` in `01_identity`, then
`npm run lint && npm run build` in both frontends.

---

## Part B — CEO Command Center

### Data availability per widget

✅ data exists today · ⚠️ needs small schema additions (Phase 2) · ❌ needs new data (Phase 3)

| # | Widget | Status | Source |
|---|---|---|---|
| KPI | Total Revenue | ✅ | Revenue: issued invoices, `taxable_total` (net of tax, same rule as Management actuals) |
| KPI | Sales Pipeline | ✅ | Revenue: open `opportunities.expected_value` |
| KPI | Receivables | ✅ | Revenue: `invoices.balance_due` |
| KPI | Active Work Units | ✅ | Delivery: `work_units` |
| KPI | Total Clients | ✅ | Revenue: `clients` |
| KPI | Total Employees | ✅ | People: `workers` |
| KPI | Business Health % | ✅ | Management: KPI results (scorecard), weighted average of goal status |
| KPI | Total Expenses | ⚠️/❌ | Payroll (People) + `cost_entries` (Delivery) + POs (Fixly) + `asset_costs` (Assets). Other operating expenses → Phase 3 |
| KPI | Total Profit | ⚠️/❌ | Revenue − Total Expenses |
| 1 | Revenue by business segment | ⚠️ | By vertical ✅ (`offerings.vertical_id`, `fact_revenue.vertical_id`). Private/Govt × India/International needs client `country` (B2.2). Hardware/AMC/Services needs offering `product_line` (B2.3) |
| 2 | Revenue & profit trend | ✅ / ⚠️ | Monthly revenue ✅. Profit line after expenses |
| 3 | Business by company | ⚠️ | Organizations under the Fillip client + `relationship` (B2.1) + cross-org rollup (B1.1) |
| 4 | Business from associates | ⚠️ | Decision 1: work units with `partner_organization_id` (B2.4) + `subcontract` cost entries |
| 5 | Geography (India) by state | ✅ / ⚠️ | Revenue by state ✅ from `invoices.place_of_supply`. Clients and projects by state need client `state_code` (B2.2, backfilled from the GSTIN's first two digits) |
| 6 | Client type & segment | ⚠️ | `client_type` already has `government`. Add `country`. AMC clients = clients with an active contract where `contract_type = 'amc'` ✅ |
| 7 | Procurement & purchase | ✅ (Fixly) | Fixly `/purchase-orders`, `/goods-receipts`. On/over budget compares against Management `budgets` ✅. Needs one Fixly summary endpoint (B1.3) |
| 8 | Hardware business | ⚠️ | Revenue from `product_line = hardware` invoice lines (B2.3). Units sold/installed from Fixly devices. Active AMC ✅ |
| 9 | AMC & services | ✅ | AMC contracts, AMC-contract invoices, `renewals` (pending, due within 30 days) |
| 10 | Field employees (technicians) | ✅ / ⚠️ | Total and available from Fixly `technicians` (`isAvailable`) ✅. On leave from People absences ✅. On field vs at office needs attendance `work_location` (B2.5) |
| 11 | Finance & investment income | ❌ | Phase 3 (B3.2) |
| 12 | Expense analysis | ⚠️/❌ | Salaries ✅ payroll, procurement ✅ Fixly, project costs ✅ `cost_entries`, software ✅ Assets `subscriptions`/`licenses`. Office, travel, marketing → Phase 3 (B3.1) |
| 13 | Freelancer network | ⚠️ | People `employment_type` gets `freelancer` (B2.6). Categories from Management `skills`, active work from `allocations` |
| 14 | Key alerts & approvals | ✅ | Control approvals (pending), overdue receivables, delivery risks and SLA alerts, renewals due, Fixly open repairs |
| 15 | Decision matrix & AI | 🔮 Future scope | Not built now. See "Future scope" at the end. The slot on the dashboard is left out of v1 |
| — | Global search, notifications | ✅ | Existing `search` and `notifications` features |

---

### Phase B1 — Command Center v1 with existing data (~1 week)

**B1.1 Gateway screen** `GET /api/bff/v1/screens/ceo?from=&to=&compare=previous_period`
- File: `00_gateway/routes/screens.py`, following the pattern of `services/aggregation_service.py` used by `/home`.
- Every API today is scoped to one organization (`X-Organization-Id`). The gateway lists the orgs
  the caller belongs to under their client, calls each service once per org **in parallel**, and sums.
- Each section is returned independently with `available: true/false`. A service that is down
  greys out its card instead of showing zero (same rule as Management's `actuals_available`).
- Every money value includes `previous` so the UI can show the "vs last month" deltas.

**B1.2 Summary endpoints, one per service** (read-only, cheap aggregates, no row lists)

| Service | Endpoint | Returns |
|---|---|---|
| Revenue | `GET /summaries/revenue` | revenue, receivables, pipeline, client count, revenue by month / vertical / state / client_type / contract_type, AMC (active, renewals due) |
| Delivery | `GET /summaries/delivery` | active work units, at-risk work units, cost entries by category |
| People | `GET /summaries/people` | headcount by employment type, on leave today, payroll total for the period |
| Management | `GET /summaries/health` | scorecard health %, budget vs actual |
| Control | existing approvals list (`pending`, count) | — |
| Assets | `GET /summaries/costs` | software and asset costs for the period |

Each endpoint follows `.agents/AGENT_PERMISSIONS.md`: a `<service>.summary.read` permission code in
Identity's catalog, a `require_permission` guard, and a test that the route is guarded.

**Business Health** (decision 5), computed in Management's `GET /summaries/health`:
- Score each KPI result for the period by its threshold status: on track = 100, at risk = 50,
  off track = 0.
- Weight each KPI by its `goal_kpis` weight (equal weights when none is set) and take the
  weighted average across all goals for the period.
- Labels: ≥ 85 Excellent · ≥ 70 Good · ≥ 50 Needs attention · < 50 Critical.
- With no KPI results for the period, return `available: false`. The card then reads
  "Set up your scorecard" instead of showing 0%.

**B1.3 Fixly summary endpoint** `GET /api/inventory/v1/reports/summary`
(`fixly/fixly_backend/src/modules/inventory/routes/reports.js`). It returns PO totals by status and
category, GRN counts, devices installed in the period, technicians (total / available) and open
repairs. Fixly serves only `FBOS_ORGANIZATION_ID` (the operator org) and answers 404
`ORGANIZATION_NOT_SERVED` for any other org. The gateway calls it once with the Fillip org ID,
not once per org.

**B1.4 Permissions (decision 6: the system administrator decides who sees what)**
- `insight.ceo_dashboard.read`: open the Command Center and see the non-sensitive cards.
- `insight.ceo_dashboard.financials`: also see sensitive figures (payroll, expenses, profit,
  margins, budgets, investments). Without it those cards show "No access" and the gateway leaves
  their numbers out of the response, so they are not merely hidden in the UI.
- Both are in Identity's permission catalog and in **no role preset by default**. Only the system
  administrator holds them out of the box, and grants them to any role or person through the
  existing Access editor (`features/access`).
- A card that also needs a service's own read (for example `revenue.invoice.read`) is shown only
  if the person holds that too. The gateway forwards the caller's token, so every service still
  applies its own permissions.

**B1.5 Frontend** `fbos_frontend/clientadmin/src/features/ceo/`
- A `CommandCenter` page (lazy route), cards read through `useQuery(['ceo-summary', clientId, range])`.
- Date range picker and "This Month" selector; each card links to its owning page (one product,
  connected flows).
- Charts follow the existing chart conventions in clientadmin. Cards that have no data yet show
  "Not set up yet" instead of fake numbers.
- Sidebar: a "CEO Command Center" entry visible only with `insight.ceo_dashboard.read`.

### Phase B2 — Small schema additions (~1 week)

Every new column is nullable or has a default, so nothing existing breaks.

| # | Service | Change | Unlocks |
|---|---|---|---|
| B2.1 | Identity `organizations` | `relationship` String(20), default `own`, values `own` / `associate` / `investment` | Widgets 3, 4 |
| B2.2 | Revenue `clients` | `country` (ISO-2, default `IN`), `state_code` (GST state code); backfill `state_code` from the GSTIN's first two digits | Widgets 1, 5, 6 |
| B2.3 | Revenue `offerings` | `product_line` String(30), nullable: `hardware` / `software` / `services` / `amc` / `training` / `other` | Widgets 1, 8 |
| B2.4 | Delivery `work_units` | `partner_organization_id` UUID, nullable (the associate doing the work) | Widget 4 |
| B2.5 | People `daily_attendance` | `work_location` String(20), nullable: `office` / `field` / `remote` | Widget 10 |
| B2.6 | People worker schema | Add `freelancer` to the allowed `employment_type` values (schema only; the column is already a string) | Widget 13 |

Each change ships with its migration, schema and form update in clientadmin, and tests.

### Phase B3 — Expenses & Finance (~2 weeks, **approved: new `11_finance` service**)

Fixly covers purchases, but **only hardware**: `PurchaseOrderItem` requires a `deviceModelId`.
Office rent, travel, marketing, subscriptions bought outside Assets, and investment income have
no home today.

Decision: a new small **`11_finance` service** (port 8011, `/api/finance/v1`). It uses the same
structure as the other services, authenticates through Identity's `/internal/authz/actor`, and
uses `finance.expense.*`, `finance.investment.*` and `finance.summary.read` permissions. It holds only:

- **B3.1 Expenses:** `expense_categories`, `expenses` (org, category, amount, tax, date, vendor
  name, paid status, optional `work_unit_id` / `org_unit_id`, attached document), and an approval
  via Control above a threshold.
- **B3.2 Investments & other income:** `investments` (type FD / MF / equity in company / property,
  principal, start/maturity) and `income_entries` (interest, returns, rent, dividend; linked to an
  investment where there is one).

The dashboard's Total Expenses is then:
payroll + `cost_entries` + Fixly PO totals + asset costs + `11_finance` expenses,
**without double counting.** A Fixly PO or an asset cost is never re-entered as an expense; the
expense form says so.

Unlocks: KPI Total Expenses/Profit and widgets 2 (profit line), 11 and 12.

### Phase B4 — Speed (after B3)
- **B4.1** A nightly job writes each section's totals to Insight `metric_daily`
  (`08_insight/models/analytics.py`). The trend charts and comparisons read snapshots instead of
  fanning out live.

---

## Order and estimate

| Phase | Scope | Estimate |
|---|---|---|
| A | Fillip unlimited | 1–2 days |
| B1 | Command Center v1 (all ✅ cards) | ~1 week |
| B2 | Schema additions → ⚠️ cards light up | ~1 week |
| B3 | `11_finance`: expenses + investments → ❌ cards light up | ~2 weeks |
| B4 | Snapshots in Insight | ~3 days |
| — | Decision matrix / Ask FBOS AI | Future scope, not scheduled |

Part A has no dependencies and can ship first.

## Future scope (not in this plan's delivery)

These are recorded so the design leaves room for them. **They are not built now.**

- **Decision Matrix (widget 15):** recommended next actions, for example "follow up on ₹X
  receivables", "N projects at risk of delay" or "renewals due". It would start with rules over the
  same summary data and add the Claude API later. The AI would read only the summary JSON, never
  raw records.
- **Ask FBOS AI (header button + widget 15 button):** questions in plain language, answered over
  the summary endpoints with the caller's own permissions, so it can never reveal more than the
  person could already see.
- **Room left for them now:** the B1 summary endpoints return clean, permission-filtered JSON.
  Both features can be built on top of those endpoints later without changing them.

## Resolved questions (2026-11-03)
1. **`11_finance`:** approved as a new service for non-hardware expenses and investments (B3).
2. **Business Health %:** weighted Management scorecard KPI status (formula in B1.2).
3. **Access:** the system administrator grants `insight.ceo_dashboard.read` and
   `insight.ceo_dashboard.financials` to whoever they choose. Neither is in a default preset (B1.4).

## Progress
- [ ] A — Fillip unlimited: A1–A6, A8, A9 done 2026-11-03 (migration `b6d8f0a2c4e5`, tests in
  `01_identity/tests/test_client_unlimited.py`). **A7 interim (2026-11-03):** on live, Fillip (client
  `FT`) was raised from 2 orgs / 100 users / ends 2027-10-07 to the highest values the current code
  accepts: 1000 / 10000 / 2099-12-31. **After Identity with migration `b6d8f0a2c4e5` is deployed:**
  `UPDATE clients SET max_organizations = NULL, max_users_per_org = NULL, subscription_end = NULL
  WHERE code = 'FT';` (NULL before that deploy would break the old code's subscription check).
- [ ] B1 — Command Center v1: built and tested 2026-11-03, not deployed. Summary endpoints:
  Revenue `GET /summaries/revenue`, Delivery `GET /summaries/delivery`, People `GET /summaries/people`,
  Management `GET /summaries/health`, Assets `GET /summaries/costs`, Fixly `GET /reports/summary`
  (reuses `inventory.report.read`); gateway `GET /api/bff/v1/screens/ceo`; clientadmin `/ceo`.
  **To ship:** restart Identity (new catalog codes), set the gateway's `INTERNAL_SERVICE_TOKEN` and
  `INVENTORY_ORGANIZATION_ID`, deploy Fixly. Business health picks one planning period: the shortest
  containing the period's last day, else the latest overlapping one. Group health = average company.
- [ ] B2 — Schema additions: built and tested 2026-11-03, not deployed. Migrations: Identity
  `c7e9a1b3d5f6` (organizations.relationship), Revenue `e4b8c2f6a9d1` (clients.country/state_code,
  backfilled from the billing address, else the GSTIN; offerings.product_line), Delivery `a8c4e2d6f0b3`
  (work_units.partner_organization_id), People `d9f1b3c5e7a2` (daily_attendance.work_location);
  `freelancer` employment type (worker create/update now accept only the five known types).
  Revenue summary adds revenue by segment / product line / project and customers by segment / state;
  Delivery adds partners (subcontract costs per associate); People adds working_today; the gateway adds
  `associates` (margin = associate projects' revenue − subcontract costs, financials only) and companies
  by relationship. Client country follows the tax engine: tax profile first, then billing address.
  Not done: projects by state (Delivery would need the customer's state).
- [ ] B3 — `11_finance` (expenses + investments): built and tested 2026-11-03, not deployed. New service
  `src/v1/11_finance` (port 8011, `/api/finance/v1`, database `fbos_finance`, migration `f1a2b3c4d5e6`):
  expense categories (12 built in, no hardware / salary / project-cost category), expenses, investments,
  income entries, settings (`expense_approval_threshold`), `GET /summaries/finance`, and
  `/internal/subject-access` so documents attach to expenses and investments. Codes `finance.expense.read|write|approve`,
  `finance.investment.read|write`, `finance.setup.manage`, `finance.summary.read` (reads sensitive).
  **Approval is local, not via Control:** no service sends approvals to Control today (Control has no
  callback to the requesting service), so an expense above the threshold waits for someone with
  `finance.expense.approve` who did not record it, like Revenue's quotation approval. Gateway: `operating_expenses`
  component in Total Expenses (`complete` is now true when all five sources answer), `finance` section,
  `alerts.expenses_awaiting_approval`. Profit stays revenue − expenses; other income is shown beside it.
  Revenue's `finance/` package (tax engine, numbering, settlement) stays in Revenue: it runs inside invoice,
  quotation and payment transactions. **To ship:** create database `fbos_finance` on Hostinger and the service's
  `.env` on the server, deploy (start.sh runs the migration), restart Identity (new codes), add
  `finance` to Documents' `SUBJECT_SERVICES` there (compose already does). clientadmin screens: `/expenses`,
  `/investments`, `/finance-setup` (`features/finance`); the Command Center cards link to them.
- [ ] B4 — Snapshots in Insight
- Future scope: Decision Matrix, Ask FBOS AI

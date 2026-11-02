# FBOS — how it was built, in phases, and what was decided

This one document replaces the earlier plan and design docs in `docs/` (multi-tenancy, tax and
billing, tax and finance research, finance integration, Fixly v2 integration, the People
architecture and implementation plans, the frontend integration guide, and the Fixly system docs).
Appendix A lists where each one went. The full original text of every removed file stays in git history:
the last commit that contains them is `2522df7` in `fbos_services` (`git show 2522df7:docs/<file>`) and `2450e2d` in
`fbos_frontend` (`git show 2450e2d:docs/fixly-v2/<file>`).

The forward-looking plan for roles, multiple posts and identity sync is kept as its own file:
[`people-roles-posts-identity-plan.md`](people-roles-posts-identity-plan.md).
The database reference stays in [`schema/`](schema/). Working rules for contributors stay in
`CLAUDE.md`, `AGENTS.md` and `.agents/`.

Written 2026-10-30. Where the older docs disagreed with the code, the code and the later decision won.

---

## At a glance

| Phase | What | State |
|---|---|---|
| 0 | Platform foundation: 10 services behind a gateway, shared API conventions, permission model | Built |
| 1 | Three-tier multi-tenancy (platform admin → client → organization) | Built |
| 2 | Revenue: tax engine and quote-to-cash finance | Phases 0–4 built; compliance and purchase side not built |
| 3 | Delivery: cross-team tasks, workflows, project templates, custom fields | Phases 0–E3, F1–F3, G1 built; rest of G and H open |
| 4 | Fixly v2 inventory connected to FBOS | Phases 0–4 built (bridge, read UI, writes, service); 5–6 open |
| 5 | People (HR): employees, recruitment, attendance, leave, payroll, exit | Built, then extended 2026-10-30 (below) |
| 6 | Next: posts, identity sync, approvals through Control | Planned (separate file) |

---

## Phase 0 — Platform foundation

**What it is.** Ten Python (FastAPI) services under `src/v1/`, each independently runnable, behind one
API gateway. The frontend (`fbos_frontend`: `clientadmin` and `superadmin`) talks only to the gateway
in production, or straight to the services through a dev proxy.

| # | Service | Base path | Domain |
|---|---|---|---|
| 00 | Gateway | `/api/bff/v1` | routing, aggregated screens |
| 01 | Identity | `/api/identity/v1` | auth, organizations, users, org units, roles, permissions |
| 02 | Revenue | `/api/revenue/v1` | CRM, quotations, contracts, billing, tax |
| 03 | Delivery | `/api/delivery/v1` | work units, tasks, workflows, time |
| 04 | Control | `/api/control/v1` | approvals, SLAs |
| 05 | Documents | `/api/documents/v1` | files and their links to records |
| 06 | Communication | `/api/communication/v1` | notifications, inbox, webhooks |
| 07 | Management | `/api/management/v1` | planning, KPIs, capacity |
| 08 | Insight | `/api/insight/v1` | audit, analytics |
| 09 | Assets | `/api/assets/v1` | IT assets, licences, credentials |
| 10 | People | `/api/people/v1` | HR (Phase 5) |

**Conventions every service follows** (these are what a frontend developer needs to know):
- Headers: `Authorization: Bearer <token>`, `X-Request-Id` for tracing, `X-Idempotency-Key` on critical
  creates, `X-Organization-Id` to act in a chosen organization.
- Lists are cursor pages: `{ "data": [...], "page": { "next_cursor", "has_more", "limit" } }`; default
  limit 25, max 100.
- Errors are RFC 7807 problems: `type`, `title`, `status`, `code` (use this in the UI), `detail`,
  `instance`, `request_id`, `retryable`.
- Auth: login (with optional MFA) returns a 15-minute access token and a rotating refresh token; on
  `TOKEN_EXPIRED` the client refreshes once and replays. The refresh token is an HttpOnly cookie in the
  web consoles. Seed users and passwords are in each service's `seed.py` (development only).
- Interactive API docs: each service serves Swagger at `/docs` on its own port.

**Decisions**

| Decision | Why |
|---|---|
| Services call Identity (`/internal/authz/actor`) with a shared `X-FBOS-Internal-Token` instead of trusting forwarded headers | Identity runs the real checks (token, revoked session, active user, organization); no service trusts caller-supplied ids |
| Permissions are codes `<service>.<entity>.<action>`; roles are only presets of codes | Fine-grained, auditable access; new codes reach admins automatically on Identity start |
| `SENSITIVE_READ_CODES` keeps other people's private data out of the `member` preset | A new `.read` code must not leak prices, security logs or cross-customer data |
| Every route is guarded; a test fails if one is not | The rule is enforced, not remembered |
| Each service migrates only its own database; never run migrations against the shared remote databases from a dev machine | Dev and live share the Hostinger databases today; separating them is a go-live item |

---

## Phase 1 — Three-tier multi-tenancy (built, Identity only)

```
Platform Admin (independent table, no org or client)
   └─ Client (customer account)
        ├─ Organization A ── users, roles, org units …
        └─ Organization B
```

| Decision | Why |
|---|---|
| The platform super-admin lives in its own `platform_admins` table, not in `users` | It owns no organization; it only manages Clients |
| `organizations.client_id` is NOT NULL, `ON DELETE RESTRICT` | No parentless organizations; a client cannot be deleted out from under its organizations |
| Two separate logins: `POST /auth/platform/login` and `POST /auth/login` | The two worlds never entangle; the platform token has no `org_id` claim |
| `require_platform_admin` checks `platform_admins` in the database on each call | A revoked admin loses access immediately, not at token expiry |
| `require_client_admin` admits `client_admin` users only | The platform admin manages Clients, not organizations (strict separation) |
| Creating a Client creates its first Organization and can invite its first client admin | One entry point builds the hierarchy; the seed creates only the permission catalog and the super-admin |
| Downstream services are untouched | They derive the tenant from the organization id, which Identity still supplies |
| Additive JWT claims (`user_type`, `client_id`) | Existing tokens and services keep working |
| Super-admin has an access token only (no refresh, no MFA) in the first cut | Can be added later without touching the hierarchy |
| `org_units.path` and `role_assignments.scope_path` use prefix indexes (255) | A full index on 2048 characters exceeded InnoDB's limit under utf8mb4 |

---

## Phase 2 — Revenue: tax engine and quote-to-cash

Planned 2026-10-05 (billing plan), researched 2026-10-09, **phases 0–4 built 2026-10-09**.

**The idea.** Nothing tax-specific is hardcoded. The code holds mechanisms; rates, states, sections,
thresholds, number formats and deadlines are dated data. A March and an April invoice use different
rules forever, and issued documents freeze a snapshot of their tax lines.

**Sub-phases**

| Step | Contents | State |
|---|---|---|
| 0 Foundation | Decimal money helpers, `finance_settings` per organization, the organization's own tax registrations (GSTIN check) | Built |
| 1 Config and engine | Dated `tax_config_entries` (9 kinds), revisions, packs (`core`, `in_gst`, `in_itd`, YAML) with diff-and-apply, pure engine, lint and overlap checks, calculation preview | Built |
| 2 Documents | Quotations, invoices, credit and debit notes on the engine; frozen per-line taxes; numbering from series per registration; credit notes copy the original and never mark it paid | Built |
| 3 Staged billing | Contract activation builds a billing schedule from payment terms; ready-to-bill list; bill a line → draft invoice | Built |
| 4 Receivables | Per-invoice TDS and GST-TDS on a payment; TDS receivables with reconciliation status; collections chase the net expected; GST-vs-cash report | Built |
| 5 Compliance | Ledger mapping and accounting export, e-invoice adapter, GSTR-1 export, reminders | Not built |
| 6 Later | Purchase side (vendor bills, TDS we deduct, RCM, ITC), a second country pack, external tax provider | Not built |

**Defects the rebuild removed** (found in the old code): hardcoded supplier GSTIN and state, always
18% on read-back and on credit notes, credit note marking the invoice paid, invoice numbers from
`count()+1`, float money, TDS as one number per payment, two duplicate tax calculators, and a billing
path that did not match the API spec.

**Decisions** (the build changed some plan items; these win)

| # | Decision | Why |
|---|---|---|
| 1 | Billing stays at `/api/revenue/v1` with `revenue.*` codes | No client breaks; the `finance/` package boundary keeps a later move cheap |
| 2 | The organization's tax registrations live in Revenue, not Identity | Every reader is billing; no network call to issue an invoice; Identity's tables were empty and changing them means migrating the shared database |
| 3 | One `tax_config_entries` table (kind, code, dates, validated JSON), not a table per kind | One API, one history, one pack applier, one as-of query; strict validation per kind |
| 4 | Pack upgrades are reviewed (diff, then apply); only an organization's first use applies the defaults | Tax changes must be seen by a person |
| 5 | Default billing mode is staged (`full_upfront` and `manual` exist) | GST follows the invoice; staging keeps GST close to cash |
| 6 | Credit-note deadline blocks by default; `warn_with_reason` allows it with a stored reason | The law blocks; the organization with its CA may record exceptions |
| 7 | Manual rate override on a document: not built | Easiest way to get tax wrong; nothing needs it |
| 8 | Purchase side goes in the same `finance/` package later | The config model already covers sections, deductee types and RCM |
| 9 | E-invoice provider (GSP): not chosen | Phase 5 |
| 10 | Invoice numbers are unique per supplier registration (GSTIN), not per organization | GST rules require uniqueness per GSTIN per financial year |
| 11 | The TDS deductee is the organization (type is a setting, PAN from its registration); lower-deduction certificates stay on the customer | The customer deducts from us, so our details decide the rate |
| 12 | A payment term's `due_offset_days` sets the drafted invoice's payment due date, not when it is billed | It is what the contract schema already meant |
| 13 | A bare GST rate from older clients maps to the plain category with that rate, never a reverse-charge one | Found by a failing test: 18% mapped to legal services under RCM |

**Before deploying finance:** have a chartered accountant confirm the pack rates, sections and dates;
every organization must add its GSTIN before billing; Identity must restart (new permission codes) and
Revenue's migration must run; `pyyaml` is a new dependency.

**Frontend (clientadmin, built):** Tax setup, Tax reports (GST vs cash, TDS withheld), Ready to bill,
generic tax totals on documents, a Tax tab on customers, payments with TDS per invoice.

**Still open:** receipt vouchers and the proforma step, 26AS import and auto-matching, impact preview
of a config change on open drafts, approval through Control for large invoices and write-offs,
milestone events from Delivery, and everything in steps 5–6 above.

### Research behind it (condensed)

Everything a company touches falls into five buckets: indirect tax on supply (GST), withholding on
payments out (TDS), withholding on payments in (TDS the customer holds back, which is a prepayment of
our income tax), direct tax on profit, and payroll statutory (PF, ESI, professional tax). GST and TDS
are mostly other people's money passing through the company; income tax is the company's own cost.

The research marked each fact by confidence. All sources were secondary (tax blogs and vendor sites,
not the statute), so **every rate and threshold is seed data to be verified by a chartered accountant
before anything is charged, deducted or filed.**

Gaps the research found beyond the sales side: a vendor master and purchase documents, vendor tax
profiles, a TDS-payable engine, RCM and import of services, ITC reconciliation, GST ledger and
liability, payroll statutory, fixed assets and depreciation, advance tax, bank reconciliation, expense
claims, a compliance calendar, and multi-currency. Open questions that decide what to build next:
legal form and turnover band, products vs services, export business, payroll in-house or outsourced,
government customers, whether FBOS is the ledger of record or feeds Tally/Zoho, who files returns,
and whether it serves one company or many.

---

## Phase 3 — Delivery: tasks across many teams

Plan approved 2026-10-08. Each phase: backend PR merged and deployed first, checked on the live
server, then the frontend PR. Migrations are additive; anything that changes how work flows is behind
a per-company Delivery setting, off by default.

**Decisions (the owner's)**
1. "Domain" = the team (org unit) does the work; vertical and discipline decide which team (routing rules).
2. People with "own records only" task access still see their teams' unassigned queue.
3. Managers assign only inside the task's team; across teams only by handover.
4. Workflows: built-in templates per discipline; each company may copy and edit them (versioned).
5. Separating production databases from dev is a go-live item, not a blocker.
6. Anyone may ask other teams for work their routing rules accept (`delivery.task.request`, in the member preset).
7. Task time limits (SLAs) stay in Delivery; Control's SLA module is not used for tasks.
8. Escalation: assignee → team head → the head of the unit above (levels without a head are skipped).

**Phases**

| Phase | What | State |
|---|---|---|
| 0, A, B, C, D | Stabilise; foundation; people and scope; visibility and "My work"; routing, requests, assignment policies | Live |
| E1 | Task notifications through an outbox and a worker (live server only) | Live |
| E2a, E2b | Time-limit alerts, escalation, team-head notices; limits counted in working hours from Identity's calendars | Live |
| E3 | Recurring-task runner (RFC 5545 rules) | Live; no screen yet |
| F1–F3 | A workflow per task type; six ready-made task workflows; the workflow builder | Built |
| G1 | Finished sales tasks appear on Revenue timelines (the fifth setting) | Built |
| Project templates, custom fields per form | Versioned project templates; custom fields per form with rules | Built (2026-10-12) |
| G (rest), H | Reports, domain packs, team lead view; optional skill and capacity assignment | Open |

Open question: on the new-task form, should a project's own team beat a routing rule? Today the rule wins.
Known gap: a due date set from a time limit is not recalculated when the task is handed to a team with
another calendar.

---

## Phase 4 — Fixly v2 inventory connected to FBOS

Plan 2026-10-14, system as of 2026-10-21. Fixly (Node, live) stays the **system of record for hardware
inventory**, exposed as an FBOS-conformant service at `/api/inventory/v1`; the UI moves into the FBOS
console. **No shared database**: the two sides reference each other by UUID.

**Options considered**

| Option | Verdict |
|---|---|
| Share one database | No: Prisma and Alembic would fight, live Fixly would be coupled to FBOS migrations, tenancy models differ |
| Rewrite inventory in Python inside `09_assets` | No for now: throws away a working live backend; `09_assets` is a different domain |
| Fixly backend as an FBOS-conformant service, UI in FBOS | **Chosen** |

**Decisions**: customer sign-in as a `client_user` with unit-scoped grants (sites are org units); the
service is named `inventory`, not `assets`; Fixly web stays until the FBOS console reaches parity;
approvals stay Fixly-internal first (Control integration later); `09_assets` keeps IT/corporate assets
and does not grow a second hardware lifecycle. A `client_user` with an organization-wide grant sees
nothing (fails closed), and records outside the caller's scope answer 404, never 403.

**Phases**

| Phase | Scope | State |
|---|---|---|
| 0 | Decisions and a spike (unit-scoped grant through `/internal/authz/actor`) | Done |
| 1 | Additive v2 schema in Fixly, backfill, lifecycle events | Done |
| 2 | Identity catalog (31 `inventory.*` codes, sensitive reads), gateway entry, FBOS auth adapter, reads, Documents subject-access, read pages | Done |
| 3 | Procurement and movement: vendors, models, purchase orders, goods receipt, transfers, installations | Done |
| 4 | Service: issues, warranty, repairs, replacement, disposal | Done |
| 5 | Links to Revenue contracts and invoices, Delivery projects and tasks, Control approvals | Not built on the FBOS side: no endpoints read or write them yet |
| 6 | Contract the legacy: redirect Fixly web, drop old columns | Open |

**Live-system rules.** Additive migrations only until phase 6; a feature flag per FBOS page
(`VITE_INVENTORY_PAGES`; production shows nothing until set); every backfill rehearsed on a throwaway
local database; rollback is the flag off with the legacy routes still served.

**FBOS-side changes.** Identity: the codes, `SENSITIVE_READ_CODES`, and the endpoints Fixly calls
(`/internal/authz/actor?with_units=true`, `/internal/people`); deploy Identity first. Gateway:
`inventory` added to the service map. Documents: `SUBJECT_SERVICES` includes `inventory`, and Fixly
answers `/internal/subject-access/{type}/{id}` for six record types (Fixly downtime blocks attaching
files to them). Communication: no change; Fixly's outbox worker posts notifications with a
`source_event_id` so a retry never notifies twice.

**Tenancy mapping.** One Identity organization runs the hardware business (`FBOS_ORGANIZATION_ID` on
Fixly). A customer is an org unit (`companies.fbos_org_unit_id`), a site is an org unit under it
(`clients.fbos_org_unit_id`), users map through `fbos_user_id`. Money: costs are sent only with
`inventory.cost.read`.

**Risks tracked**: customers leaking across customers (cross-customer test on every list endpoint);
new `.read` codes auto-granted to members (add to `SENSITIVE_READ_CODES` in the same change); two auth
systems during transition (separate routers, no shared token); dual-write drift (one owner per concept);
event delivery gaps (outbox plus idempotent consumers).

**Console pages** (`features/inventory`): Devices, Stock, Transfers, Purchasing, Device issues,
Repairs, Disposals, Inventory reports. Reads use `useQuery`; state changes send `If-Match`; goods
receipts and dispatches send an `Idempotency-Key`; dates are ISO timestamps (use `formatDay`).

---

## Phase 5 — People (HR)

### 5.1 The design

People covers the full employee lifecycle: positions and job architecture, recruitment (structured
hiring), onboarding, attendance and overtime, leave, payroll and expenses, appraisals and bonuses,
and exit. It is built on benchmarks from large systems: **Workday** (position management, business
processes), **UKG** (rounding rules), **SAP SuccessFactors** (foundation objects), **Greenhouse**
(structured interviews and blinded scorecards), **Rippling** (zero-touch identity and IT lifecycle),
and statutory standards (US FLSA, Indian Factories Act). Policy is inherited
organization → vertical → unit → position.

**Overtime rules** (four gates): overtime starts only after 30 continuous minutes beyond the shift;
time rounds in 15-minute steps with the 7/8-minute neutral rule; clocking in early does not count;
overtime needs a linked task and manager approval. Executives and engineers marked not overtime-eligible
get comp-off leave instead of cash. Attendance: 8 hours or more is present, 4–8 half day, under 4 absent.

### 5.2 The plan and how it went

| Planned phase | State |
|---|---|
| 1 Service skeleton, gateway, positions, workers | Built |
| 2 Recruitment and structured ATS | Built |
| 3 Zero-touch onboarding (create login, assign hardware, vault documents) | Partly: a hire creates the employee and writes events for Identity and Assets to an outbox; **nothing consumes those events yet** |
| 4 Shifts, attendance and the overtime engine | Built |
| 5 Leave ledger (double-entry) | Built |
| 6 Salary structures, payroll runs, payslips, expense claims | Built |
| 7 Hikes, bonuses, promotions | Built; promotions replaced by role changes (below) |
| 8 Separation, clearance matrix, full-and-final | Built; **the midnight login deactivation is not implemented** (the finalize screen says it is) |
| 9 Client-admin frontend | Built |

### 5.3 What was added on 2026-10-30

| Piece | What | PRs |
|---|---|---|
| Add from users | HR creates employee records from existing active Identity employee users, in batches; one worker per user; employee code optional | services #73, frontend #53 |
| HR screens restyled | The pages used Tailwind classes but Tailwind is not installed, so they rendered unstyled; rebuilt on the app's own form, table and dialog classes with shared `FormDialog` and `Field` | frontend |
| IDs, bank, onboarding | Per-document records (PAN, Aadhaar, passport, licence, voter ID, UAN, ESIC, address proof, education, photo, offer letter, contract, NDA, relieving letter) with encrypted numbers, verification, an onboarding checklist, and bank accounts with a primary account | services #74 |
| Commit fix | Write routes in attendance, leave, payroll, progression, recruitment and separation never committed, so production would have lost those writes; fixed in 32 routes with a guard test | services #75 |
| Salary screen | Salary breakdown and a Set salary / Revise salary form | frontend #56 |
| Role changes | Promotion, demotion, transfer and correction with a second approver | services #76, frontend #57 |

### 5.4 Decisions

| Decision | Why |
|---|---|
| The employee code is optional and can be set later | Existing staff may not have one yet; the unique constraint tolerates empty values |
| One employee record per Identity user (unique per organization) | Prevents double-linking |
| Files live in the Documents service (`people.employee` subject), never in People; ID scans use a restricted category | Reuses the access checks and storage already built |
| ID and bank numbers are encrypted with `FIELD_ENCRYPTION_KEY`; only the last four are kept in clear; without a valid key the service still runs and saving or showing numbers answers 503 | A missing key must not crash the deployed service; a wrong key must not corrupt data |
| Revealing a number needs `people.compensation.read`; every reveal, edit, verify and reject is logged | Access to personal data is auditable |
| Aadhaar is stored encrypted and masked, as requested | Indian rules restrict keeping and showing Aadhaar numbers; the masking and the logging are the safeguards, and the compliance position should be checked |
| Old bank and tax columns on the worker were dropped without copying | Nothing read them and no environment held data in them |
| Verification is one tick by HR (pending → uploaded → verified / rejected); any edit sends it back for verification | Simple and safe |
| The writing route commits, tested by a guard that every write route does | Each production request gets its own session, closed without committing |
| Role changes need a second person; approving needs the new `people.role_change.approve` | A person must never approve their own change |
| A past or current effective date applies on approval; a future date waits and a worker applies it | Real HR systems are effective-dated |
| Salary goes through the same step, with promotion not cutting pay and demotion not raising it | Approvers see role and pay together |
| The position seat moves with the person and the old seat becomes vacant | Headcount stays true |
| Editing the designation in the Edit form is refused | Every role change is approved and recorded |
| Pay in a role change is hidden from people without compensation-read or approve | Field-level privacy |
| Notifications go through Communication, fire-and-forget | A notification failure never breaks a business change |

**Deploy notes for People.** Deploy Identity first (new permission codes). Set `FIELD_ENCRYPTION_KEY`
on the server and never change it. Turn on `ROLE_CHANGE_WORKER_ENABLED` and `NOTIFICATIONS_ENABLED` on
one server only. Documents' `SUBJECT_SERVICES` must include `people`.

**Not built:** notification to approvers when a request arrives (the service cannot look up who holds a
permission); a promotion-letter field in the form; a department picker for users who cannot read the
company structure. The older direct promotions endpoint remains for importing history and bypasses approval.

---

## Phase 6 — Next (planned, not built)

See [`people-roles-posts-identity-plan.md`](people-roles-posts-identity-plan.md): People as the source of
truth for department, manager and status; mapping job roles to Identity access roles; several posts per
person; approvals routed through Control; joiner, mover and leaver sync with a drift check.

---

## Decisions still open

| Area | Open |
|---|---|
| Finance | CA review of pack rates; e-invoice provider; rounding policy per organization; purchase side scope |
| Delivery | Project's own team vs a routing rule on the new-task form |
| Fixly | Who owns devices by default (customer-owned vs lent / vendor-owned); the FBOS-side links in phase 5; retiring Fixly web |
| People | The 13 decisions in the roles and posts plan; the compliance position on Aadhaar numbers; approver notifications |
| Platform | Separating production databases from dev (go-live item) |

---

## Appendix A — Where the removed documents went

| Removed file | Now |
|---|---|
| `MULTI_TENANCY_PLAN.md` | Phase 1 |
| `tax-and-billing-plan.md` | Phase 2 (design principles, defects, build order, decisions) |
| `tax-and-finance-research.md` | Phase 2, "Research behind it" |
| `finance-integration-plan.md` | Phase 2 (decisions, build status, deploy notes) |
| `fixly-v2-integration-plan.md` | Phase 4 |
| `fixly-v2/FBOS_SERVICES.md`, `fixly-v2/SYSTEM.md` | Phase 4 |
| `fbos_frontend/docs/fixly-v2/*` | Phase 4 (console pages) |
| `service_10_people_master_plan.md`, `service_10_people_implementation_plan.md` | Phase 5 |
| `FRONTEND_INTEGRATION_GUIDE.md` | Phase 0 conventions |

The full text of every removed file stays in git history (commits above). Code comments that cited section
numbers of the removed tax research now point here and name the original file, so the section numbers
still resolve with `git show`.

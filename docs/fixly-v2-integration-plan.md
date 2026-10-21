# Fixly v2 ⇄ FBOS integration plan

Status: **draft for review** · Written 2026-10-14 · Planning only, no code changed
Inputs: Eraser file "Fixly" (v2 ER design + 2 flows), `fixly/fixly_backend` (Node/Express/Prisma/MariaDB, live), `fbos_services` (FastAPI, 10 services), `fbos_frontend/clientadmin` (React/Vite).

---

## 0. Recommendation in one paragraph

Keep the **Fixly backend (Node)** as the system of record for hardware inventory and lifecycle, and make it behave as an **FBOS-conformant service** (`/api/inventory/v1`): callers are authenticated through FBOS Identity, access is per-user permissions (`inventory.<entity>.<action>`), errors and pagination use FBOS shapes, and changes are published as events. The **UI moves into `fbos_frontend/clientadmin`** as a new `features/inventory` module. Fixly stays live on its legacy `/api/v1` and mobile app until each piece is cut over. **No shared tables and no shared DB**; the two sides reference each other by UUID and exchange data through APIs and events. Build it additively (expand → migrate → contract) because Fixly is live and FBOS is not.

---

## 1. Where each side is today

| | Fixly (live) | FBOS (in development) |
|---|---|---|
| Stack | Node 20, Express, Prisma, MariaDB, Socket.IO, FCM; React web + Flutter mobile | Python FastAPI, 10 services, Alembic, React clientadmin/superadmin |
| Auth | Own `users` table, 5 fixed roles (`super_admin, client_admin, zone_incharge, zone_staff, technician`), JWT (7-day), `requireRole()` + `authz/scope.js` | Identity service; services call `/internal/authz/actor` with `X-FBOS-Internal-Token`; per-user permission codes; roles are presets only |
| Tenancy | Company → Client(site) → Zone tree | Identity Client (tenant account) → Organization → Org units; Revenue "client" = customer |
| Inventory | `devices` mixes model and unit; no stock, vendor, PO, warranty, repair | `09_assets`: generic IT-asset register (tags, custodian, vendor accounts, credentials). Thin: placeholder names, no lifecycle, no procurement |
| Data | 445 devices, 5 companies, 4 sites, 227 zones, 9 users, 8 issues | Shared remote MySQL for identity/revenue — **never run migrations against it from a dev machine** |

**Naming collisions to settle before any code (glossary):**

| Word | In Fixly | In FBOS |
|---|---|---|
| Company | customer organization (e.g. Rajgir Zoo Safari) | — (closest: Revenue **client** = customer) |
| Client | a customer's site/facility | Identity **Client** = tenant account that owns organizations; Revenue **client** = customer |
| Organization | — | the operating company in Identity |
| Zone | nested area inside a site | — |

Proposal: in v2 vocabulary Fixly **Company → "customer"**, Fixly **Client → "site"**, Zone stays "zone". The FBOS-facing API never says "client" for a site.

---

## 2. Target architecture

```
 fbos_frontend/clientadmin ── /api/identity ─────► Identity (auth, orgs, users, permissions)
        │  features/inventory
        │  /api/inventory ────────────────────────► Fixly backend  (inventory service, Node)
        │  /api/revenue, /api/delivery, /api/documents ... (unchanged)
        │
 Flutter app (technicians) ── legacy /api/v1 now ──► Fixly backend  (moves to inventory API later)

 Fixly backend ──► Identity   GET /internal/authz/actor      (who is calling, what may they do)
 Fixly backend ──► Documents  files for devices, POs, GRNs, repairs, disposals
 Fixly backend ──► Communication  /internal/notifications  (in-app inbox; FCM stays for mobile)
 Fixly backend ──► outbox events ──► Revenue / Delivery / Control / Insight
 Revenue / Delivery ──► Fixly   internal calls + events (contract signed, project installed)
```

### Options considered

| Option | Verdict |
|---|---|
| A. Share one database between Fixly and FBOS | **No.** Prisma and Alembic would fight over the schema; live Fixly would be coupled to FBOS migrations; tenancy models differ. |
| B. Rewrite inventory in Python inside `09_assets` | **No for now.** Throws away a working live backend, and `09_assets` is a different domain (IT assets, credentials). Revisit only if the team wants one language. |
| C. Fixly backend exposed as an FBOS-conformant service, UI in FBOS | **Recommended.** Backend investment kept, UI and identity unified, each side deploys on its own. |

### Boundary with `09_assets`
`09_assets` keeps IT/corporate assets (software, subscriptions, credentials, vehicles). Field hardware with lifecycle (cameras, displays, networking) lives in the inventory service. Do not build a second hardware lifecycle in `09_assets`. If one register view is wanted later, publish read-only events from inventory into it.

---

## 3. Identity and tenancy mapping (the hard part)

| Fixly | FBOS | How |
|---|---|---|
| The hardware business itself (platform / CEO) | an Identity **Organization** | every inventory row gets `organization_id` = the operating org |
| Company (customer) | Revenue **client** (customer) | `companies.fbos_customer_id` (Revenue client UUID) |
| Client (site) | stays a Fixly table (renamed "site" in API) | keyed by customer; owned by inventory |
| Zone tree, installations | stay in inventory | owned by inventory |
| Fixly users (platform staff, technicians) | Identity users | `users.fbos_user_id`; Fixly stores only ids, names resolved from Identity like Delivery does |
| Customer staff (client_admin, zone_incharge, zone_staff) | Identity users with `user_type = client_user` in the vendor org | scoped with per-user grants (`scope_unit_id`, `self_only`) |

**D1 — how customer-side people sign in (verified in code, recommendation below):**
- Identity already has `user_type = client_user` ("someone from one of your customers who needs limited access"; `01_identity/schemas/user.py:10`, free string column, no migration). Permissions are per user with `scope_unit_id` and `self_only` (`models/user_permission.py`), and `/internal/authz/actor` returns `permissions`, `own_records_only`, `unit_scopes`.
- **Rejected: one Identity organization per customer.** `max_organizations` defaults to 2, and the vendor would have no cross-org view.
- **Recommended: customer staff are `client_user`s in the vendor org.** Model each customer **site** as an org unit (customer → site) and grant inventory permissions with `scope_unit_id`; zones stay inside inventory. Scope then comes through `unit_scopes` instead of a new concept.
- **Fallback (b-lite):** if sites are not modelled as units, use `self_only` grants plus site/zone assignments held in inventory.
- **Must check in the Phase 0 spike:** `client_user` is only a label today. Each service's list endpoints must apply `unit_scopes` themselves, so a missed filter leaks one customer's data to another.

Technicians today belong to no organization. In FBOS they become `contractor` or `employee` users of the vendor org; coverage stays in `technician_assignments`.

---

## 4. System of record per concept

| Concept | Owner | Others hold |
|---|---|---|
| Users, organizations, permissions, sessions | Identity | id only |
| Customer (company) master, contacts, tax profile, contracts, invoices | Revenue | `fbos_customer_id` on inventory customer row |
| Devices, models, vendors, POs, GRNs, stock, transfers, installs, warranties, repairs, disposals, issues, visits, daily logs | Inventory (Fixly backend) | read via API; events out |
| Installation projects / work orders, tasks | Delivery | `work_unit_id`, `task_id` stored on installation / repair |
| SLA clocks, approvals | Control | `approval_request_id`, `sla_policy_id` |
| Files | Documents | `document_id` + `entity_type` / `entity_id` |
| In-app notifications | Communication | — |
| Audit trail across services | Insight (fed by events) | `device_lifecycle_events` stays the device-level history |

---

## 5. Contracts both sides must honour

1. **Auth.** Fixly new router forwards `Authorization` + `X-Organization-Id` to Identity `GET /api/identity/v1/internal/authz/actor` with `X-FBOS-Internal-Token`; relays 401/404; answers 503 if Identity is down. Short in-memory cache (the legacy `authenticate` already uses 30 s). Never read org or user from any other header.
2. **Permissions.** Codes `inventory.<entity>.<action>` added to Identity's `PERMISSION_CATALOG` (`services/permission_catalog.py`). **Every `.read` code joins the `member` preset automatically** and `SENSITIVE_READ_CODES` is a hard-coded set, so any code exposing cost, price, vendor terms, disposals or other customers' data must be added to that set **in the same Identity change**, or it leaks to every member. Identity must be deployed before inventory routes ship. Node cannot reuse the Python unguarded-route test, so Fixly needs its own test that walks the router and fails on a route without `requirePermission`.
3. **Record-level rules** (own site/zone, assigned technician, "own records only") live in the Fixly service layer on top of the permission, using `own_records_only` and `unit_scopes` from the actor.
4. **Wire shapes.** Errors `{ "detail": { "code", "message", "meta" } }`; pages as `PageResponse`; resource URLs plural nouns; `If-Match`/`version` for concurrent edits; `Idempotency-Key` on transfers, GRN registration, repair dispatch.
5. **Ids.** UUIDs everywhere; cross-system references are plain UUID columns, no FK, validated by API call at write time.
6. **Events — what really exists.** FBOS has **no event bus**. The mechanism is a per-service outbox table plus a polling worker that makes HTTP calls to a named destination (`03_delivery/models/outbox.py`, `services/outbox_worker.py`). Communication takes `POST /internal/notifications` with `source_event_id` for dedup; Revenue takes activity pushes. So v2 starts with: an outbox in the inventory DB + a Node worker that POSTs **notifications to Communication** (and, later, explicit per-target endpoints that FBOS services add). `processed_events` and a general event catalog are deferred until some service actually consumes events. Candidate events once consumers exist: `device.received|installed|retired`, `transfer.dispatched|received`, `issue.raised|resolved`, `repair.sent|returned`, `warranty.expiring`.
7. **Documents.** `05_documents` holds no ACLs; it calls the owning service at `GET {base}/internal/subject-access/{type}/{id}?action=read|attach` with `Authorization`, `X-Organization-Id`, `X-FBOS-Internal-Token` (`05_documents/services/subject_client.py`). A 200 returns `{organization_id, label}`; 403/404/409/422 are relayed. Inventory implements this in Node with subject types `inventory.device`, `inventory.purchase_order`, `inventory.goods_receipt`, `inventory.repair_order`, `inventory.disposal`, `inventory.issue`, and Documents gets a `subject_services` config entry (default has only `revenue`). Each upload hits inventory, so Fixly downtime blocks file attach and read; return an org mismatch as 404.
8. **Money.** Currency + GST on PO lines and repair costs, aligned with Revenue's tax model; base currency from the organization (not `USD`).

---

## 6. Changes to the Eraser ER design (v2 → v2.1)

| # | Change | Why |
|---|---|---|
| 1 | **Replace the role capability matrix with permission codes + presets.** Roles `inventory_manager`, `company_storekeeper`… become presets, never checked in code. | FBOS is user-based, not role-based. The matrix in §8 is role-based. |
| 2 | Add `organization_id` to every table (operating org), plus `customer_id` where a row belongs to a customer. | FBOS tenancy; the doc only has company/client. |
| 3 | Replace FKs to `users` with plain `*_user_id` UUIDs (Identity ids). Drop the Fixly `users`/`refresh_tokens` from the long-term model; keep `fbos_user_id` mapping during transition. | Identity is the single source of users. |
| 4 | Add `fbos_customer_id` on `companies`; rename `clients` → `sites` in the v2 API. | Remove the "client" collision. |
| 5 | Add platform tables: `outbox`, `idempotency_keys` (and `code_sequences` at Phase 6). `processed_events` only when a consumer exists. | FBOS conventions; reliable notifications. |
| 6 | Add `version int` on mutable aggregates (`devices`, `stock_transfers`, `repair_orders`, `issues`). | Optimistic concurrency. |
| 7 | `device_documents.file_url` → `document_id` (Documents service). Keep `doc_type`. | Documents is the central hub. |
| 8 | Add integration columns: `device_installations.work_unit_id/task_id`, `warranties.contract_id`, `repair_orders.billable/invoice_id`, `issues.sla_policy_id/approval_request_id`, `purchase_orders.approval_request_id`, `device_disposals.approval_request_id`. | Link to Delivery, Revenue, Control. |
| 9 | **Add `maintenance_plans` + generated preventive visits (AMC).** v2 covers corrective maintenance; "preventive" exists only as a `visit_type`. | The stated goal includes maintenance. |
| 10 | Technicians: allow non-org contractors; keep `technician_assignments` as coverage. | Fixly technicians are org-less today. |
| 11 | Currency default from the organization; add `tax_percent` + HSN/SAC on model. | Billing correctness. |
| 12 | **Keep `devices.status` as is and add `lifecycle_state` as a new column** (not an enum alteration). Retire `status` at Phase 6. | Changing a MariaDB enum is not additive; it locks and rewrites the table, and the legacy app reads `status`. |
| 13 | **Replace `Issue → Device` cascade with Restrict, and add soft-delete (`deleted_at`) before any v2 write.** | v1 deletes a device's issues and history with it (schema.prisma:331). The doc's rule 14 says never cascade, but the live schema does. |
| 14 | **Zone deletion must be blocked or rejected while devices are installed.** `Device.zone` is `SetNull`, which today silently turns the unit into "stock". | Under the v2 location model this corrupts stock and custody. |
| 15 | Keep the existing `code` generator (`reserveCodes` on `ProductCategory.last_seq`) while legacy routes are live; move to `code_sequences` only at Phase 6. | Monotonic, unique codes. |

---

## 7. Work in Fixly (backend, web, mobile)

**Backend (`fixly_backend`)**
- Additive Prisma migrations for the v2 tables and nullable columns (Eraser doc §9 steps 1–9); legacy endpoints keep working untouched.
- Backfill scripts (idempotent, `--dry-run`, run first on a restored copy).
- New `src/modules/inventory/*` mounted at `/api/inventory/v1`: FBOS auth adapter, `requirePermission`, FBOS error/pagination shapes, outbox publisher, Documents/Communication clients.
- Replace role checks in new code with permission checks; leave `authz/scope.js` for legacy until retired. Mount legacy and new routers separately so the two auth stacks never share middleware.
- Map the 9 Fixly users to Identity users by email (Identity email is globally unique); force password reset instead of migrating hashes. Keep Fixly `User` rows as a mapping layer, because `Technician.user` cascades from `User`.
- Outbox table + polling worker (none exists in Node today) that POSTs to Communication.
- `fbos_*` link columns and a small `fbos_links` table for mapping audit.
- Health/readiness endpoint and an OpenAPI file for the contract.

**Web (`fixly_frontend`)**: freeze feature work; keep running for current customers until FBOS UI reaches parity, then redirect.

**Mobile (`fixly_flutter`)**: stays on legacy `/api/v1` through Phases 1–3. Phase 4 moves it to FBOS Identity sign-in and the inventory API. Identity already supports it: `/token/refresh` accepts a body refresh token when the request sends `X-Client-Type: mobile` (`01_identity/routes/auth.py`). The app must store the refresh token and serialize refreshes (reuse revokes the whole session family).

## 8. Work in FBOS

**Identity**: add `inventory.*` codes **and** matching `SENSITIVE_READ_CODES` entries in one change; deploy before inventory routes. Customer users use the existing `client_user` type with unit-scoped grants (D1); add an internal lookup for people by ids if missing.

**Revenue**: customer ↔ inventory link (`fbos_customer_id`); internal read for customer + sites contacts; later: contract warranty/AMC terms, billable repairs → invoices.

**Delivery**: optional link from installation/replacement to a project or task; no duplicate technician task system.

**Control**: later, approvals for PO, repair cost and disposal; SLA for issues.

**Documents / Communication / Insight**: new entity types, notification templates, audit consumers.

**Gateway**: `00_gateway/routes/proxy.py` has a static `SERVICE_URL_MAP` of 9 services, so inventory needs a map entry and a setting in `00_gateway/config.py`. The proxy forwards all headers, so inventory must never trust forwarded identity headers. In dev, a Vite proxy `INVENTORY_URL` is enough.

**Documents**: add `inventory` to `subject_services` config (`05_documents/config.py`).

**Frontend (`clientadmin`)**: new `features/inventory/` with `api.js`, pages (Devices, Device detail + timeline, Stock locations, Transfers, Vendors/Models/POs/GRN, Warranties, Issues & visits, Repairs, Disposals, Dashboard), access gating through `features/auth/access.js`, `DocumentPanel` for files, id→name lookups like `useDeliveryNames`. Add `/api/inventory` to the Vite proxy and CLAUDE.md.

---

## 9. Phases and gates

| Phase | Scope | Exit gate |
|---|---|---|
| 0 Decisions + spike | D1–D5 answered; glossary; OpenAPI; permission list. One-day spike: a `client_user` with a unit-scoped grant calling a Node endpoint through `/internal/authz/actor` | Spike passes; sign-off |
| 1 Foundation | v2 schema additive in Fixly (`lifecycle_state` column, cascade → Restrict, soft delete, zone-delete guard); backfill; lifecycle events; legacy app unaffected | Counts reconcile (445 devices, 5/4/227); legacy smoke passes |
| 2 Bridge + read UI | Identity catalog + `SENSITIVE_READ_CODES`, gateway entry, FBOS auth adapter, `/api/inventory/v1` reads, Documents `inventory.*` subject-access, Devices/Locations/Timeline pages | FBOS user with permission sees devices; a `client_user` sees only their site; unguarded-route test green |
| 3 Procurement and movement | Vendors, models, PO, GRN, transfers, allocations, installations (writes) | A device walks PO → GRN → company → client → zone in FBOS UI |
| 4 Service | Issues, visits, warranty lookup, repair orders, replacement, disposal; mobile moves to Identity | Fault-to-resolution flow incl. RMA; technician app on new API |
| 5 Cross-service | Revenue/Delivery/Control/Insight links (new inbound endpoints on the FBOS side), maintenance plans, event consumers if wanted | Contract → install → warranty → billable repair end to end |
| 6 Contract legacy | Redirect Fixly web, remove legacy role code, drop old columns | No traffic on legacy routes for 2 weeks |

**Live-system rules:** additive migrations only until Phase 6; feature flag per FBOS page; every backfill rehearsed on a throwaway local DB first; never run Alembic or Prisma migrate against the shared remote DBs from a dev machine; rollback = flag off + legacy routes still served.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Customer users leak across customers: `client_user` is a label, each service must apply `unit_scopes` itself | Phase 0 spike; cross-customer test in every list endpoint |
| New `.read` codes auto-granted to all members | Add sensitive codes to `SENSITIVE_READ_CODES` in the same change |
| Device cascade deletes issues; zone delete turns units into stock | Phase 1 fixes before any v2 write |
| No outbox worker in Node, no event consumers in FBOS | Notifications-only first; consumers are new FBOS work |
| Documents calls inventory synchronously on every attach | Health + timeouts; accept that downtime blocks attach |
| Two auth systems during transition | Legacy and new routers separate; no shared token |
| Dual writes drift (users, customers) | One owner per concept (§4); sync by events; reconcile job |
| Prisma + Alembic schema ownership confusion | Strict rule: each service migrates only its own DB |
| Live data quality (344 `'null'` specs, missing prices/dates) | Cleanup step before backfill; required fields at receiving |
| Event delivery gaps | Outbox + idempotent consumers + replay |

## 11. Decisions needed

Advisor review (highest-tier model, checked against the code) agrees with the recommendations below; D3 is a business fact only you can confirm.

- **D1** Customer sign-in: `client_user` in the vendor org with unit-scoped grants (sites as org units; b-lite fallback). **Recommended.**
- **D2** Service name `inventory`, not `assets`. **Recommended.**
- **D3** Who owns the devices: customer-owned by default with lent/vendor-owned as the exception? **Needs your answer** (sets `ownership_type` default and billing).
- **D4** Keep Fixly web until FBOS reaches parity, then retire on a set date. **Recommended.**
- **D5** Approvals Fixly-internal first; Control integration later. **Recommended.**

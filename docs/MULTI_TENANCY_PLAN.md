# FBOS — 3-Tier Multi-Tenancy Implementation Plan

> **Status**: In progress (Phases 1–2 implemented)
> **Scope**: `src/v1/01_identity/` only — no other service requires changes
> **Branch**: `gkr`
> **Date**: 2026-09-29

---

## 1. Goal

Introduce a three-tier tenancy hierarchy so a platform-level super-user can onboard
customer accounts ("Clients"), and each Client can manage one or more Organizations
underneath it.

```
Platform Admin
    │  creates
    └─ Client: Acme Corp
           │  creates
           ├─ Org: Acme India ──── Users, Roles, OrgUnits…
           └─ Org: Acme US    ──── Users, Roles, OrgUnits…
```

- **Platform Admin** — cross-tenant super-user. Creates and manages Clients, and can
  act on any Organization.
- **Client** — a customer account (tenant). Owns one or more Organizations.
- **Organization** — the existing operational tenant. Everything downstream
  (users, roles, revenue, delivery, …) is already scoped to an Organization via the
  `X-FBOS-Org-Id` header the gateway injects.

### Why downstream services are untouched

Every other service derives its tenant from `X-FBOS-Org-Id` (see the API reference
"tenant guard" section). The Client tier sits *above* the Organization and is resolved
entirely inside the Identity service, so revenue/delivery/etc. continue to operate on
an `organization_id` exactly as they do today.

---

## 2. Current State (baseline)

| Concern | Today |
|---|---|
| Organization model | Flat table, no parent, no client link |
| User model | Mandatory `organization_id`; `user_type` defaults to `"employee"` |
| Roles | Scoped to a single organization |
| Org creation | Only via `seed.py` — no API endpoint |
| Super-user | Does not exist |
| Client tier | Does not exist |

> Note: "Client" already exists in the **Revenue** service as a CRM entity (a company
> you sell to). That is unrelated to this tenancy Client and lives in a different
> service/table. No naming collision at the DB level.

---

## 3. Target Design

### 3.1 Data model

**New table `clients`**

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR(255) NOT NULL | |
| `code` | VARCHAR(100) UNIQUE NOT NULL | slug, e.g. `ACME` |
| `contact_email` | VARCHAR(255) NULL | |
| `status` | VARCHAR(50) NOT NULL default `active` | |
| `created_at` | DATETIME NOT NULL | |

**Modified table `organizations`** — add one nullable FK

| Column | Type | Notes |
|---|---|---|
| `client_id` | UUID NULL | `FK clients.id ON DELETE SET NULL` |

`client_id` is nullable so the existing seeded `FILLIP` organization (and the new
`PLATFORM` org) keep working without belonging to a Client.

### 3.2 Token claims

`create_access_token` gains two optional params, emitted as JWT claims:

- `user_type` — `"platform_admin"`, `"client_admin"`, or `"employee"`
- `client_id` — present when the user belongs to a Client-owned org

`TokenPayload` gains matching optional fields plus helper properties
(`is_platform_admin`, `is_client_admin`, `client_uuid`). Because `TokenPayload` uses
`extra="ignore"`, adding claims is **non-breaking** for existing tokens and services.

### 3.3 Authorization guards

Two new FastAPI dependencies in `dependencies.py`:

- `require_platform_admin` — allows only platform admins.
  **DB-verified**, not token-only: this is a cross-tenant super-user privilege, so a
  demoted admin must lose access immediately rather than retaining it until the 15-min
  access token expires.
- `require_client_admin` — allows **only** client admins. Organization-level actions
  belong exclusively to the client; the platform super-admin manages clients, not
  their organizations (strict separation). Also DB-verified, for the same reason —
  it grants privileged org management, so a stale token must not keep working.

### 3.4 Org bootstrap (critical correctness step)

Today the `admin`/`member` roles and their permission rows exist only because
`seed.py` creates them for the default org. A freshly created org would have **no
roles**, so its first admin would land with zero permissions and could not invite
anyone.

A shared helper `_bootstrap_org(session, org_id, admin_user_id=None)` will, in the same
transaction as org creation:

1. Create the standard `admin` (system) and `member` roles for the new org.
2. Attach their `RolePermission` rows.
3. If an admin user id is given, create the `RoleAssignment` granting them `admin`.

Called from both `create_client` (for its auto-created first org) and
`create_organization`.

---

## 4. API Surface (new endpoints)

All under the Identity base path (`/v1` and `/api/identity/v1`).

### Clients — platform admin only

| Method | Path | Guard | Success |
|---|---|---|---|
| POST | `/clients` | platform admin | 201 + `Location` |
| GET | `/clients` | platform admin | 200 (paginated) |
| GET | `/clients/{client_id}` | platform admin | 200 |
| PATCH | `/clients/{client_id}` | platform admin | 200 |

### Organizations — client admin only

The platform super-admin cannot reach these endpoints (strict separation). The
`client_id` is always taken from the caller's token, never from the request body.

| Method | Path | Guard | Notes |
|---|---|---|---|
| POST | `/organizations` | client admin | new org is created under the caller's own client |
| GET | `/organizations` | client admin | auto-scoped to the caller's client |
| GET | `/organizations/{org_id}` | client admin | ownership-checked against caller's client |
| PATCH | `/organizations/{org_id}` | client admin | ownership-checked against caller's client |

Creating a Client auto-creates its first Organization (same name/code) and, if an
`admin_email` is supplied, invites the first `client_admin` user into that org. This
bootstrap happens inside the client service (a server-side call), so it is unaffected
by the `require_client_admin` guard on the public `POST /organizations` endpoint.

> Responsibility split: **superuser → clients only**; **client admin → organizations,
> users, roles**. A client's first org + first client_admin are provisioned
> automatically when the superuser creates the client, so the client is
> self-sufficient from then on.

---

## 5. Error Codes (new)

Added to `exceptions.py` and registered in `main.py`'s `_PROBLEM_META`.

| Code | HTTP | Meaning |
|---|---|---|
| `PLATFORM_ADMIN_REQUIRED` | 403 | Caller is not a platform admin |
| `CLIENT_ADMIN_REQUIRED` | 403 | Caller is not a client/platform admin |
| `CLIENT_NOT_FOUND` | 404 | No such client |
| `CLIENT_CODE_EXISTS` | 409 | Duplicate client code |
| `ORGANIZATION_NOT_FOUND` | 404 | No such organization |
| `ORGANIZATION_CODE_EXISTS` | 409 | Duplicate organization code |

All follow the existing structured error shape (`code`, `message`, `status`, …).

---

## 6. File Change Summary

17 files, all within `src/v1/01_identity/`. No other service changes.

| File | Change | Phase |
|---|---|---|
| `models/client.py` | **NEW** — Client model | 1 ✅ |
| `models/organization.py` | + `client_id` FK column | 1 ✅ |
| `models/__init__.py` | Register `Client` with `Base.metadata` | 1 ✅ |
| `utils/security.py` | + `user_type`, `client_id` params in `create_access_token` | 2 ✅ |
| `schemas/token.py` | + `user_type`, `client_id`, helper properties | 2 ✅ |
| `dependencies.py` | Pass new claims through `get_current_user` | 2 ✅ |
| `schemas/auth.py` | + `user_type`, `client_id` in `Me` | 3 |
| `services/auth_service.py` | Pass new claims at 3 call sites + `_build_me` | 3 |
| `dependencies.py` | + `require_platform_admin`, `require_client_admin` | 4 |
| `schemas/client.py` | **NEW** — request/response schemas | 5 |
| `schemas/organization.py` | **NEW** — request/response schemas | 5 |
| `exceptions.py` | + 6 error classes | 6 |
| `main.py` | Register 6 error codes in `_PROBLEM_META` | 6 |
| `services/organization_service.py` | **NEW** + shared `_bootstrap_org` helper | 7 |
| `services/client_service.py` | **NEW** | 7 |
| `routes/clients.py` | **NEW** | 8 |
| `routes/organizations.py` | **NEW** | 8 |
| `router.py` | Mount both new routers | 8 |
| `seed.py` | Add `PLATFORM` org + platform-admin user | 9 |

---

## 7. Build Order

Phases have no circular dependencies; build top-down.

1. **Data layer** ✅ — `models/client.py`, `organization.py` FK, `models/__init__.py`.
2. **Token layer** ✅ — `utils/security.py`, `schemas/token.py`, `dependencies.py` claim passthrough.
3. **Auth plumbing** — pass new claims in `login` / `verify_mfa` / `refresh_session`
   and expose them in `_build_me` + `Me`.
4. **Guards** — `require_platform_admin`, `require_client_admin` in `dependencies.py`.
5. **Schemas** — `schemas/client.py`, `schemas/organization.py`.
6. **Errors** — `exceptions.py`, `main.py`.
7. **Services** — `organization_service.py` (incl. `_bootstrap_org`), then
   `client_service.py`. *This is the most correctness-critical phase.*
8. **Routes + wiring** — `routes/clients.py`, `routes/organizations.py`, `router.py`.
9. **Seed** — platform admin bootstrap.

---

## 8. Seed / Bootstrap

`seed.py` appends (idempotently):

- **Platform org**: `name="FBOS Platform"`, `code="PLATFORM"`, `client_id=NULL`.
- **Platform admin user**: `email="superadmin@fbos.platform"`,
  `user_type="platform_admin"`, `status="active"`, password `Password@123`.

This is the single entry point from which all Clients and their Organizations are
created via the API.

---

## 9. Design Decisions & Trade-offs

- **Platform user as a system org, not a parallel `PlatformUser` table.** Reuses the
  existing `User`/credential/auth machinery; the platform admin is simply a `User`
  with `user_type="platform_admin"` in the `PLATFORM` org.
- **Additive JWT claims.** `extra="ignore"` keeps existing tokens and downstream
  services working unchanged.
- **Strict superuser/client separation.** The platform super-admin manages Clients
  only and cannot act on organizations; `require_client_admin` therefore admits
  `client_admin` alone (not `platform_admin`). A client's first org and first
  client_admin are bootstrapped server-side at client-creation time, so the client is
  self-sufficient without the superuser reaching into org endpoints.
- **DB-verified admin guards.** Both `require_platform_admin` and
  `require_client_admin` re-check the caller's `user_type`/`status` in the DB (a cheap
  PK lookup) rather than trusting the token claim alone, so a demoted admin loses
  access immediately instead of at token expiry.
- **Guard exceptions landed in Phase 4, not Phase 6.** `PLATFORM_ADMIN_REQUIRED` and
  `CLIENT_ADMIN_REQUIRED` were added with the guards (they can't function without
  them) and registered in `_PROBLEM_META`. The remaining four service-layer errors
  (client/org not-found and code-exists) still land in Phase 6.
- **`client_id` nullable on `organizations`.** Keeps existing/seed orgs valid and lets
  the platform org exist outside any Client.
- **Organization `version` / ETag.** `organizations` currently has no `version`
  column. `PATCH /organizations/{id}` will **not** require `If-Match` in this first
  cut (deviates from the users/roles convention); revisit if optimistic concurrency
  becomes necessary.

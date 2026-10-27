# FBOS — 3-Tier Multi-Tenancy

> **Status**: Implemented
> **Scope**: `src/v1/01_identity/` only — no other service requires changes
> **Branch**: `gkr`

---

## 1. Goal

A three-tier tenancy hierarchy in which an independent platform super-admin onboards
customer accounts ("Clients"), and each Client manages one or more Organizations.

```
Platform Admin  (independent — its own table, no org/client)
    │  creates
    └─ Client: Acme Corp
           │  creates
           ├─ Org: Acme India ──── Users, Roles, OrgUnits…
           └─ Org: Acme US    ──── Users, Roles, OrgUnits…
```

- **Platform Admin** — cross-tenant super-user. **Independent**: it is *not* a `User`
  and belongs to no organization or client. It only creates/manages Clients.
- **Client** — a customer account (tenant). Owns one or more Organizations.
- **Organization** — the operational tenant. Everything downstream (users, roles,
  revenue, delivery, …) is scoped to an Organization via the `X-FBOS-Org-Id` header the
  gateway injects. **Every Organization must belong to a Client.**

### Why downstream services are untouched

Every other service derives its tenant from `X-FBOS-Org-Id`. The Client tier sits *above*
the Organization and is resolved inside Identity, so revenue/delivery/etc. keep operating
on an `organization_id` exactly as before.

---

## 2. Data Model

**`platform_admins`** (NEW) — the independent super-admin. No org/client columns.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `email` | VARCHAR(255) UNIQUE NOT NULL | |
| `name` | VARCHAR(255) NOT NULL | |
| `password_hash` | VARCHAR(255) NOT NULL | argon2id (inline; access-token-only auth) |
| `status` | VARCHAR(50) NOT NULL default `active` | |
| `created_at` | DATETIME NOT NULL | |

**`clients`** (NEW)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR(255) NOT NULL | |
| `code` | VARCHAR(100) UNIQUE NOT NULL | slug, e.g. `ACME` |
| `contact_email` | VARCHAR(255) NULL | |
| `status` | VARCHAR(50) NOT NULL default `active` | |
| `created_at` | DATETIME NOT NULL | |

**`organizations`** — gains a **mandatory** client FK.

| Column | Type | Notes |
|---|---|---|
| `client_id` | UUID **NOT NULL** | `FK clients.id ON DELETE RESTRICT` |

`client_id` is NOT NULL with no exceptions — the super-admin is independent and never
owns an org, so there is no parentless-org case to accommodate. `ON DELETE RESTRICT`
prevents deleting a Client out from under its orgs.

---

## 3. Authentication

Two separate, non-entangled login paths:

| Caller | Endpoint | Table | Result |
|---|---|---|---|
| Platform super-admin | `POST /auth/platform/login` | `platform_admins` | access token (no refresh/MFA) |
| Regular org user | `POST /auth/login` | `users` | access + refresh (+ MFA) — unchanged |

The platform token carries `sub`, `email`, `user_type="platform_admin"` and **no**
`org_id`/`client_id` claim (`create_access_token` omits `org_id` when it is `None`).
`TokenPayload.org_id` is already optional, so `get_current_user` handles it unchanged.

### Guards (`dependencies.py`)

- `require_platform_admin` — DB-verifies the caller against **`platform_admins`**
  (`status = active`), not `users`. A revoked admin loses access immediately rather than
  at token expiry.
- `require_client_admin` — admits `client_admin` users only (verified against `users`).
  The platform super-admin manages Clients, not organizations (strict separation).

### Org bootstrap

`OrganizationService.bootstrap_org(session, org_id, admin_user_id=None)` gives a new org
its RBAC baseline (system `admin` role wired to the full permission catalog, `member`
role, and the first admin's `RoleAssignment`) in the same transaction as org creation.
Called from `create_client` (first org) and `create_organization`.

---

## 4. API Surface

| Method | Path | Guard |
|---|---|---|
| POST | `/auth/platform/login` | public (credentials) |
| POST/GET/GET/PATCH | `/clients`, `/clients/{id}` | platform admin |
| POST/GET/GET/PATCH | `/organizations`, `/organizations/{id}` | client admin (auto-scoped to the caller's client) |

Creating a Client auto-creates its first Organization (same name/code) and, if
`admin_email` is supplied, invites the first `client_admin`. `client_id` for orgs is
always taken from the caller's token, never the request body.

---

## 5. Seed

`seed.py` bootstraps only:

- **Permission catalog** — global rows consumed by `bootstrap_org`.
- **Platform super-admin** — one `platform_admins` row: `superadmin@fbos.platform` /
  `Password@123`, `status=active`.

No orgs or clients are seeded — those are created through the API. This is the single
entry point from which the whole hierarchy is built.

---

## 6. Notes

- **Schema is built by `create_all`** (no Alembic migrations). `org_units.path` and
  `role_assignments.scope_path` are `String(2048)`; a full-column index on them exceeds
  InnoDB's 3072-byte limit under `utf8mb4`, which aborted `create_all`. They now use
  **prefix indexes** (`Index(..., mysql_length=255)`), so `create_all` completes in one
  pass and the startup seed runs cleanly on a fresh DB. `mysql_length` is ignored by
  SQLite, so tests are unaffected.
- **Additive JWT claims** (`user_type`, `client_id`) with `extra="ignore"` keep existing
  tokens and downstream services working unchanged.
- **Access-token-only super-admin.** No refresh/MFA in this cut; the super-admin
  re-authenticates when the short-lived access token expires. Refresh/MFA can be added
  later without touching the tenant hierarchy.

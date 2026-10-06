# Permissions — Agent Guidelines

## Rule

**Every change to a service that adds or changes an endpoint also adds its permissions, in the
same change.** No route ships unguarded, and no permission code ships without being in
Identity's catalog.

Apply this whenever you:

- add a route, or a new action on an existing resource;
- touch a service that still trusts headers for who is calling (`X-FBOS-Org-Id`,
  `X-FBOS-User-Id`, a `DEFAULT_ORG_ID` fallback) — move it to Identity first (step 1);
- change what an existing route does (a read that starts writing, a new power on a resource).

The reference implementation is `src/v1/03_delivery` (Revenue, `src/v1/02_revenue`, follows the
same pattern).

---

## 1. Authenticate through Identity (once per service)

Copy these from Delivery, renaming the base error to the service's own:

- `services/identity_client.py`: `Actor` and `IdentityClient`. It forwards the caller's
  `Authorization` and `X-Organization-Id` to Identity's
  `GET /api/identity/v1/internal/authz/actor` with `X-FBOS-Internal-Token`. It relays Identity's
  own errors (401, 404 organization) and answers 503 when Identity can't be reached.
- `dependencies.py`: `get_identity_client`, `get_actor`, `CurrentActor`, `require_permission(code)`.
  `OrgId` and `UserId` come from the actor. Never read the organization or user from any other
  header, and never fall back to a default organization or user.
- `exceptions.py`: `AuthenticationRequiredError` (401), `PermissionDeniedError` (403, with
  `meta.required_permission`), `AuthServiceUnavailableError` (503).
- `config.py`, `.env.example` and the local `.env`: `IDENTITY_SERVICE_URL=http://identity:8000`,
  `INTERNAL_SERVICE_TOKEN` (the same value every service uses) and the Identity timeout.
- `main.py`: the lifespan opens and closes the `IdentityClient`.

## 2. Name the permissions

- Format: `<service>.<entity>.<action>`, lowercase snake_case, three parts, e.g.
  `delivery.task.read`. The entity is the resource; the action is `read`, `write` or a named
  power (`approve`, `review`, `manage`, `operate`).
- Group by what a person may do, not one code per route:
  - `read` covers every GET of the resource, and lets the person work on the records assigned
    to them (an assignee works their own task, an approver decides what waits for them).
  - `write` covers create, update and delete.
  - Separate codes only for powers you'd give to fewer people: approving, reviewing other
    people's work, setup and templates, seeing other people's private data.
- Put the codes in the service's `permissions.py` as constants, with a short module docstring.
- Add every code to Identity's catalog, `src/v1/01_identity/services/permission_catalog.py`
  (`PERMISSION_CATALOG`, entries `(code, service, description)`). The description says in plain
  words what the code lets someone do; the console's access editor shows it to admins.
- What Identity does with a new code (`ensure_permission_catalog`, on every Identity start):
  - every organization's `admin` preset, and the users holding it, get it;
  - a `.read` code also joins every organization's `member` preset. If a read exposes other
    people's private data (sessions, audit log, someone else's time), add it to
    `SENSITIVE_READ_CODES` so members don't get it.
- Never rename or remove a code that is in use without a plan for its grants: grants point at
  the code, and the shared Identity database holds every branch's codes.

## 3. Guard every route

- In each routes module: `CAN_READ = Depends(require_permission(permissions.X_READ))` (and
  `CAN_WRITE`, ...), then `dependencies=[CAN_READ]` on the route.
- Only `/health` and routes that show nothing but the caller's own data (e.g. a "my counts"
  summary) may stay open. List them in `OPEN_PATHS` in `tests/test_permissions.py`.
- Rules that depend on the record belong in the service layer, on top of the permission: the
  assignee works their own task, the named reviewer reviews, the requester cancels their own
  request; anyone else needs the broader permission.
- "Own records only" (the access editor's switch): when the caller holds a read code only for
  their own records (`actor.only_own(code)`, from Identity's `own_records_only`), filter lists in
  the query, before pagination, and answer anyone else's single record as not found (404).
  Delivery's `IN_VIEW` dependencies in `routes/tasks.py` and `routes/work_units.py` show how.

## 4. Test it

- `tests/test_permissions.py`:
  - `test_every_route_is_guarded_unless_meant_to_be_open` walks `app.routes`. A guard counts when
    its dependency's name starts with `require_`, which `require_permission` sets.
  - A parametrized 403 per route for a caller without the code.
  - The owner rules, and "own records only" where the service supports it.
- `tests/test_auth.py`: 401 without a token, the headers forwarded to Identity, Identity's error
  relayed, 503 when Identity is down.
- Identity's tests if you change the catalog's top-ups.

## 5. Ship it

- Identity must restart to add the codes (`docker compose up -d --build identity`). Its seed
  writes to the shared Identity database, so ask before restarting it.
- The console (frontend repo, `clientadmin/`) needs, in the same piece of work:
  - an `ACCESS` rule per page and action in `src/features/auth/access.js`;
  - labels in `src/features/access/permissions.js` (`SERVICE_LABELS`, `ENTITY_LABELS`) so the
    access editor names things as the sidebar does ("Projects", not "Work unit");
  - `FRIENDLY` copy for new error codes in `src/shared/api/errors.js`.
- List the new codes where the service is documented (the frontend `CLAUDE.md` lists each
  service's permissions).

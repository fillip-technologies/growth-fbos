# REST API Design Guidelines

These are binding rules for this agent whenever it designs, generates, reviews, or refactors REST API endpoints — route definitions, controllers, OpenAPI/Swagger specs, SDKs, or any code exposing HTTP endpoints. Each rule includes the reasoning, concrete examples, and what to flag in review.

---

## 1. Design around resources, not actions

**Reasoning:** HTTP methods already describe the action. If the URL *also* describes the action, you now have two competing ways to say the same thing, and they can drift out of sync.

**❌ Bad**
```
GET  /getUsers
POST /createOrder
POST /deleteProduct/5
POST /updateUserEmail
```

**✅ Good**
```
GET    /users            -> list users
POST   /orders           -> create an order
DELETE /products/5       -> delete product 5
PATCH  /users/5          -> update user 5 (e.g. email)
```

**Why it scales better:** with the resource-based design, adding a new operation on `orders` (e.g. "cancel") doesn't require inventing a new top-level endpoint name — it can often be modeled as a state change:
```
PATCH /orders/42        { "status": "cancelled" }
```
instead of inventing `POST /cancelOrder/42`.

**Exception:** actions that truly aren't CRUD on a resource (e.g. "send password reset email") are fine as a sub-resource/action verb on a POST, since they don't map to a noun cleanly:
```
POST /users/5/password-reset-email
```
This is acceptable because it's still nested under a resource and uses POST for a non-idempotent trigger — it isn't a verb *replacing* the resource name at the top level.

**Review checklist:**
- [ ] No verbs in the main resource path (`/get*`, `/create*`, `/delete*`, `/update*`)
- [ ] Every top-level path segment is a noun (resource or sub-resource)

---

## 2. Keep URLs predictable and consistent

**Reasoning:** Predictability lets a developer guess an endpoint's shape correctly the first time, without checking docs.

**❌ Bad — inconsistent naming across the same API**
```
GET /user/5
GET /customers/12
GET /customer-profile/9
```

**✅ Good — one convention everywhere**
```
GET /users/5
GET /customers/12
GET /customer-profiles/9
```

**Rules to enforce:**
- Collections are always plural: `/users`, not `/user`.
- A single resource is `/{collection}/{id}`: `/users/5`.
- Nested resources follow the same pattern: `/users/5/orders/42`.
- Pick ONE casing convention for multi-word resources and never mix it:
  - kebab-case (recommended for URLs): `/customer-profiles`
  - NOT `/customerProfiles`, NOT `/customer_profiles`, NOT `/CustomerProfiles`
- Query parameter keys should also share one casing convention (commonly `camelCase` or `snake_case` — match whatever the JSON body uses).

**Review checklist:**
- [ ] All collections are plural
- [ ] Same casing convention used in every path across the whole API
- [ ] Nested resource paths follow `/{parent}/{id}/{child}` consistently

---

## 3. Use HTTP methods for their actual semantic purpose

**Reasoning:** Clients, proxies, caches, and browsers all make assumptions based on HTTP method semantics (e.g. GET is cacheable and safe to prefetch, PUT/DELETE are safe to retry). Violating these assumptions causes subtle bugs.

| Method | Purpose | Idempotent? | Has body? |
|---|---|---|---|
| GET | Retrieve, never mutate | Yes | No |
| POST | Create a resource, or trigger a non-idempotent action | **No** | Yes |
| PUT | Replace the full resource | Yes | Yes |
| PATCH | Partially update a resource | Ideally yes | Yes |
| DELETE | Remove a resource | Yes | No (usually) |

**❌ Bad**
```
POST /users/5          # used to "update" a user — but POST isn't idempotent
GET  /users/5/delete   # using GET to trigger a mutation — breaks caching & prefetching
```

**✅ Good**
```
PUT   /users/5   { "name": "...", "email": "...", "role": "..." }   # full replace
PATCH /users/5   { "email": "new@example.com" }                     # partial update
DELETE /users/5
```

**Idempotency in practice:**
```
DELETE /orders/42   -> 204 No Content (order deleted)
DELETE /orders/42   -> 204 No Content (already gone, no error — idempotent)
```
vs.
```
POST /orders   { "sku": "ABC" }   -> 201 Created, order #101
POST /orders   { "sku": "ABC" }   -> 201 Created, order #102   ⚠️ a NEW order, not the same one
```
If clients need safe retries on POST, implement an **idempotency key**:
```
POST /orders
Idempotency-Key: 8f14e45f-...
```
The server stores the key and returns the original response on a duplicate request instead of creating a second resource.

**Review checklist:**
- [ ] GET requests never mutate state
- [ ] PUT sends a complete representation; PATCH sends a partial one
- [ ] POST is used only for creation or explicitly non-idempotent actions
- [ ] Retries on POST are protected via idempotency keys where relevant

---

## 4. Make status codes useful

**Reasoning:** The HTTP status line is the first thing a client, proxy, or monitoring tool reads. It must never contradict the body.

**❌ Bad**
```http
HTTP/1.1 200 OK
Content-Type: application/json

{ "success": false, "error": "Product not found" }
```
The transport layer says "success," the payload says "failure." Clients now must parse every 200 response body just to know if it worked.

**✅ Good**
```http
HTTP/1.1 404 Not Found
Content-Type: application/json

{ "code": "PRODUCT_NOT_FOUND", "message": "No product with id 5001", "status": 404 }
```

**Status code reference to apply consistently:**

| Code | When to use |
|---|---|
| 200 | Successful GET/PUT/PATCH with a response body |
| 201 | Resource successfully created (include `Location` header pointing to the new resource) |
| 202 | Request accepted, processing will finish asynchronously |
| 204 | Success, no response body (e.g. successful DELETE) |
| 400 | Malformed request (bad JSON, missing required field) |
| 401 | Missing or invalid authentication |
| 403 | Authenticated, but not authorized for this action |
| 404 | Resource does not exist |
| 409 | Request conflicts with current resource state (e.g. duplicate email on create) |
| 422 | Well-formed request, but fails business/validation rules |
| 429 | Client is being rate-limited |

**Example — 201 with Location header:**
```http
POST /orders
->
HTTP/1.1 201 Created
Location: /orders/101
Content-Type: application/json

{ "id": 101, "status": "pending" }
```

**Review checklist:**
- [ ] Response status always matches the actual outcome
- [ ] 201 responses include a `Location` header
- [ ] No app ever returns 200 for a failed operation

---

## 5. Keep error responses consistent and structured

**Reasoning:** A consistent error shape lets client code handle errors generically (one parser for every endpoint) instead of writing custom handling per route.

**❌ Bad — inconsistent, unstructured**
```json
"Error: invalid input"
```
```json
{ "err": "bad request", "info": "field missing" }
```
```json
{ "message": "Something went wrong" }
```
Three different endpoints, three different shapes — the client can't write one error handler.

**✅ Good — one shape, used everywhere**
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "One or more fields are invalid.",
    "status": 422,
    "details": [
      { "field": "email", "issue": "must be a valid email address" },
      { "field": "age", "issue": "must be a positive integer" }
    ]
  }
}
```

**Minimum required fields in every error response:**
- `code` — a stable, machine-readable string (e.g. `USER_NOT_FOUND`), safe for clients to branch on
- `message` — human-readable explanation, safe to show in logs or UI
- `status` — matches the HTTP status code
- `details` (optional, but required for validation errors) — field-level breakdown

**Review checklist:**
- [ ] Every error response uses the exact same top-level shape
- [ ] `code` is a stable enum-like string, not a free-text sentence
- [ ] Validation errors (422) list the specific failing field(s)

---

## 6. Don't put everything into the URL path — use query parameters correctly

**Reasoning:** The path identifies *what resource*; query parameters *refine* the result. Mixing the two makes URLs unpredictable and hard to extend.

**❌ Bad — filters stuffed into the path**
```
/products/category/shoes/instock/true/sort/price-asc/search/running
```
Adding one more filter means inventing another path segment, and clients must memorize path order.

**✅ Good — path identifies the resource, query params refine it**
```
GET /products?category=shoes&inStock=true&sort=price&order=asc&q=running
```

**Common, predictable query parameter patterns to standardize on:**
```
GET /products?page=2&pageSize=20          # pagination
GET /products?sort=price&order=asc        # sorting
GET /products?category=shoes&inStock=true # filtering
GET /products?q=running+shoes             # free-text search
GET /products?fields=id,name,price        # sparse fieldsets (optional)
```

**❌ Never use query parameters to smuggle in an action**
```
GET /products?action=delete&id=5   # forbidden — GET must never mutate
```
```
GET /products/5/delete              # also forbidden — verb in path, wrong method
```
**✅ Correct way to delete**
```
DELETE /products/5
```

**Review checklist:**
- [ ] Path = resource identity only, never filters
- [ ] Query params = filtering, sorting, pagination, search only
- [ ] No query parameter or path ever encodes a mutating "action" on a GET

---

## 7. Treat API changes as breaking-change decisions

**Reasoning:** Every response shape is an implicit contract with every client already integrated. Changing it silently breaks them in production, often without warning.

**Decision test before shipping any change:**

| Change | Breaking? |
|---|---|
| Add a new optional field to a response | ❌ Not breaking |
| Add a new optional query parameter | ❌ Not breaking |
| Add a new endpoint | ❌ Not breaking |
| Remove a field | ✅ Breaking |
| Rename a field | ✅ Breaking |
| Change a field's type (e.g. string → object) | ✅ Breaking |
| Change validation rules to be stricter | ✅ Breaking |
| Change default sort/pagination behavior | ✅ Breaking |

**Example of a breaking change that looks small:**
```json
// v1
{ "price": 19.99 }

// v2 — looks like an improvement, but it's breaking
{ "price": { "amount": 19.99, "currency": "USD" } }
```
Any client doing `response.price.toFixed(2)` now crashes, because `price` is an object, not a number.

**How to version when a breaking change is unavoidable — pick ONE strategy and apply it consistently across the whole API:**
```
# URL versioning (most explicit, easiest for clients to reason about)
GET /v1/products/5
GET /v2/products/5

# Header versioning (keeps URLs stable)
GET /products/5
Accept: application/vnd.myapi.v2+json

# Query parameter versioning (least recommended, easy to omit accidentally)
GET /products/5?version=2
```

**Migration path expectations:**
- Announce deprecation of `v1` before removing it.
- Keep the old version running in parallel for a defined window.
- Document the diff between versions explicitly (changelog, migration guide).

**Review checklist:**
- [ ] Every schema change is classified as breaking / non-breaking before merging
- [ ] Breaking changes always go through the chosen versioning strategy — never shipped in-place on an existing version
- [ ] Deprecated versions have a documented sunset date

---

## 8. Keep request/response formats consistent across the whole API

**Reasoning:** Once a developer learns one endpoint, every other endpoint should behave the same way — same date format, same casing, same pagination shape, same error shape. Inconsistency multiplies the amount a client has to remember per-endpoint.

**❌ Bad — every endpoint reinvents its own conventions**
```json
// GET /users/5
{ "created_at": "2024-01-05T10:00:00Z", "userName": "alice" }

// GET /orders/12
{ "createdAt": "01/05/2024", "user_name": "alice" }

// GET /products/9
{ "CreationDate": "Jan 5 2024", "UserName": "alice" }
```

**✅ Good — one convention, everywhere**
```json
// GET /users/5
{ "createdAt": "2024-01-05T10:00:00Z", "userName": "alice" }

// GET /orders/12
{ "createdAt": "2024-01-06T14:30:00Z", "userName": "alice" }

// GET /products/9
{ "createdAt": "2024-01-07T09:15:00Z", "userName": "alice" }
```

**Conventions to fix once and enforce everywhere:**
- **Dates/times:** always ISO 8601 UTC (`2024-01-05T10:00:00Z`), never locale-formatted strings.
- **Property casing:** pick one (`camelCase` is most common in JSON APIs) and never deviate.
- **Pagination shape** — same on every list endpoint:
  ```json
  {
    "data": [ /* items */ ],
    "pagination": { "page": 2, "pageSize": 20, "totalItems": 134, "totalPages": 7 }
  }
  ```
- **Error shape** — see Rule 5, applied identically on every endpoint.
- **Envelope consistency:** if one endpoint wraps results in `{ "data": [...] }`, all list endpoints must, not just some.

**Review checklist:**
- [ ] Date/time format is identical across every endpoint
- [ ] Property casing is identical across every endpoint and request/response
- [ ] Pagination envelope shape is identical across every list endpoint
- [ ] No endpoint uses a bespoke response envelope that others don't

---

## Pre-flight checklist (run before adding or reviewing any endpoint)

Before writing or approving a new endpoint, confirm:

1. **Resource naming** — is this a noun, plural, consistent casing with the rest of the API?
2. **HTTP method** — does the chosen method match its actual semantics (safe/idempotent/etc.)?
3. **Status codes** — does every response path (success + each error case) return the correct code?
4. **Error shape** — does every error use the API's standard `{ code, message, status, details? }` shape?
5. **Path vs. query params** — is the path resource-only, with all filtering/sorting/pagination in query params?
6. **Breaking change check** — if this modifies an existing response, is it additive-only, or does it need a new API version?
7. **Format consistency** — do dates, casing, pagination, and envelopes match every other endpoint in the API?

## Guiding principle

A REST API isn't "good" because it technically uses GET/POST/PUT/DELETE. It's good when a developer who has used *one* endpoint can correctly predict how every other endpoint behaves — without opening the docs. When generating or reviewing API code, actively flag any violation of the rules above rather than silently reproducing an inconsistent pattern already present in the codebase.

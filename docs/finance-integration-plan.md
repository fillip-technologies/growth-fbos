# Finance Integration Plan — 02_revenue

> Status: **phases 0–4 built** on branch `ayush-dev4` (2026-10-09), not committed. See
> [§19 Build status](#19-build-status-2026-10-09) for what was built, what was deferred and the
> decisions taken while building (some changed the plan below; §19 wins where they differ).
> Inputs: [`tax-and-finance-research.md`](tax-and-finance-research.md) (what the law and the money
> flow require) and [`tax-and-billing-plan.md`](tax-and-billing-plan.md) (tax tables, engine,
> documents, payments). **This document decides how it all goes into the revenue service and how it
> stays changeable**: nothing tax-specific is hardcoded, and every rule that the government or the
> business can change is data with a date on it.
>
> Where this plan and the billing plan differ, this plan wins. Where this plan says "billing plan
> §N", that section is adopted unchanged.

---

## Table of contents

1. [Decisions in one page](#1-decisions-in-one-page)
2. [What is in the code today](#2-what-is-in-the-code-today)
3. [The flexibility model](#3-the-flexibility-model)
4. [What changes when the law or the business changes](#4-what-changes-when-the-law-or-the-business-changes)
5. [Package layout inside 02_revenue](#5-package-layout-inside-02_revenue)
6. [Data model](#6-data-model)
7. [Policy settings (`finance_settings`)](#7-policy-settings)
8. [Packs: shipped, versioned, reviewed](#8-packs)
9. [Extension points (registries and adapters)](#9-extension-points)
10. [Flows mapped to code](#10-flows-mapped-to-code)
11. [Other services](#11-other-services)
12. [API](#12-api)
13. [Permissions](#13-permissions)
14. [Guardrails against hardcoding](#14-guardrails-against-hardcoding)
15. [Migration and compatibility](#15-migration-and-compatibility)
16. [Phases and PR-sized steps](#16-phases-and-pr-sized-steps)
17. [Testing](#17-testing)
18. [Open decisions](#18-open-decisions) — all resolved, see §19.2
19. [Build status (2026-10-09)](#19-build-status-2026-10-09)

---

## 1. Decisions in one page

| # | Decision | Why |
|---|---|---|
| D-1 | **Lives in `02_revenue`**, as its own package `finance/` with no imports from CRM modules except through narrow interfaces (client, offering, contract readers). | Revenue already owns invoices, payments, contracts, billing schedules. A clean package boundary means it can move to a separate billing service later without a rewrite. |
| D-2 | **Code holds mechanisms, never values.** The engine knows *how* to apply a rule; *which* taxes, rates, states, sections, thresholds, number formats and deadlines apply is data. | Rates changed in Sep 2025, TDS sections were renumbered in Apr 2026; both will change again. |
| D-3 | **Six layers of change** (§3): code → packs → org config → org policy → document override → adapters. Each change goes to the lowest layer that can hold it. | Most future changes become a config edit or a pack upgrade, not a deploy. |
| D-4 | **Everything that has legal meaning is effective-dated** (`effective_from` / `effective_to`) and evaluated "as of" the document's tax point date. | A March invoice and an April invoice must use different rules, forever. |
| D-5 | **Issued documents freeze a snapshot** of every tax line plus the config version that produced it. Config changes never rewrite history. | Audit, credit notes, re-printing. |
| D-6 | **Staged invoicing from the billing schedule is the default flow**; receipt voucher is the fallback for unexpected advances (research §7.8). Each piece is behind a policy flag. | GST follows the invoice; staging keeps tax close to cash. |
| D-7 | **Lifecycles (state machines) stay in code**; organisations switch optional steps on/off (approval, proforma, receipt voucher) through policy. | Legal states (issued is immutable, credit never means paid) must not be configurable away. |
| D-8 | **Money is `Decimal`**, stored `Numeric(18,2)`; rates `Numeric(9,4)`; rounding is per-regime config. | Floats today (defect D8). |
| D-9 | **API stays backwards compatible**: the existing `cgst/sgst/igst` fields keep working (computed from tax lines) until the frontend moves to a generic `taxes[]`. | Don't break clientadmin. |
| D-10 | **Purchase side (vendor bills, TDS we deduct, ITC, RCM) is designed for but built later**, in the same `finance/` package. The config model already covers it. | User's scope is 02; sales side is where the defects are. |

---

## 2. What is in the code today

Verified 2026-10-09 in `src/v1/02_revenue`.

| Area | Today | Problem |
|---|---|---|
| Supplier GSTIN | `invoice_service.py:237` → `"29AABCF9876L1Z3"` | Hardcoded |
| Supplier state | `"29"` defaults in `invoice_service.py:42,238-244`, `quotation_service.py:40,162,216-220,337` | Hardcoded Karnataka |
| GST rate | `quotation_service.py:73-75` parses `offering.gst_code` else `"18.0"`; `invoice_service.py:121,422` returns/uses `18.0` | Hardcoded rate, rate not stored on invoice lines |
| Fiscal year | `invoice_service.py:360` `fy = "26-27"`; `:437` `CN/26-27/...` | Hardcoded FY and prefix |
| Numbering | `count()+1` in invoices, credit notes, `payment_service.py:184-188` `RC-{year}-{n}` | Not concurrency-safe, not per GSTIN/FY; `InvoiceSeries` model exists but unused |
| Credit note | `invoice_service.py:490` sets the original to `"paid"` | Legally wrong |
| TDS | `payment_service.py:192` adds one `tds_amount` to `unapplied_amount` | No section/rate/per-invoice/receivable |
| Billing schedule | `models/billing.py` `BillingSchedule(Line)` + `contract.py` `ContractPaymentTerm` | Models exist, **nothing generates or uses them** |
| Invoice tax storage | Fixed columns `cgst/sgst/igst_total`, line `cgst/sgst/igst_amount` | Can't hold UTGST, cess, VAT, RCM, or another country |
| Money | `Mapped[float]` over `Numeric` everywhere | Float rounding |
| Identity | `legal.py` `LegalEntity`, `TaxRegistration(pin, regime_code, …)` | No routes, no state code, no LUT, no e-invoice flags |
| Accounting | `AccountingExport` tracking table only | No ledger mapping |
| Per-org settings | None in revenue; delivery has `DeliverySettings` (one row per org, every flag off by default) | Pattern to copy |

The full defect list D1–D12 is in billing plan §5.2; all of them are fixed by phases 1–3 below.

---

## 3. The flexibility model

Every rule lives in exactly one layer. Higher layers override lower ones only where the lower
layer explicitly allows it.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ L6  ADAPTERS        external providers behind interfaces                      │
│                     (tax calc provider, e-invoice GSP, accounting export,     │
│                      GSTIN lookup, 26AS import parser)                         │
├──────────────────────────────────────────────────────────────────────────────┤
│ L5  DOCUMENT        per-document override WITH a reason, audited              │
│     OVERRIDE        (place of supply, reverse charge, exemption, rate         │
│                      override if policy allows)                                │
├──────────────────────────────────────────────────────────────────────────────┤
│ L4  ORG POLICY      finance_settings: how this company runs billing           │
│                     (staged billing, proforma, receipt vouchers, rounding,    │
│                      approval threshold, credit-note deadline mode…)          │
├──────────────────────────────────────────────────────────────────────────────┤
│ L3  ORG CONFIG      effective-dated rows per organization                      │
│                     (regimes, components, rates, categories, rules,           │
│                      withholding sections, series formats, ledger accounts,   │
│                      compliance deadlines)                                     │
├──────────────────────────────────────────────────────────────────────────────┤
│ L2  PACKS           versioned YAML in the repo (India GST, India TDS, …)       │
│                     copied into L3 on bootstrap; upgrades shown as a diff      │
├──────────────────────────────────────────────────────────────────────────────┤
│ L1  CODE            mechanisms only: engine, condition matcher, rounding,     │
│                     numbering, state machines, snapshotting, validation        │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.1 What belongs in code (L1) — and nothing else

- The **engine algorithm** (billing plan §9.2): supply-type resolution, rule matching by priority,
  component evaluation in sequence, compound bases, inclusive back-calculation, rounding, withholding preview.
- The **condition vocabulary** for rules (a fixed, typed set: `supply_type`, `category`,
  `customer_registration_type`, `place_of_supply`, `customer_country`, `reverse_charge`,
  `document_type`, `amount_between`, `supplier_registration_type`). New *kinds* of condition need
  code; new *rules* never do.
- **Lifecycles**: draft → issued → partially_paid → paid; issued is immutable; credit never sets paid.
- **Numbering mechanism**: locked increment per series row; format rendering from a template.
- **Snapshotting**, **effective-date lookup**, **validation**, **error codes**.

Rule of thumb: if a CA could tell you the value, it is not code.

### 3.2 Effective dating

- Every L3 row with legal meaning has `effective_from` (inclusive) and `effective_to` (exclusive,
  nullable). Overlaps for the same code are rejected.
- The engine receives a **tax point date** and loads only rows valid on it.
- A row **used by an issued document cannot be edited**; it can only be closed (`effective_to`) and
  superseded by a new row. Unused rows can be edited freely.

### 3.3 Config versioning

- Each org has a monotonically increasing **`config_revision`**; any L3 change bumps it.
- Issued documents store `config_revision` and the ids of the rules/rates used (billing plan §10.1).
- `GET /tax/config?as_of=2026-03-31` returns exactly what applied then — for audits and credit notes.

### 3.4 Impact preview before a change goes live

Any L3 change can be **previewed**: the API re-runs the engine for the last N drafts / open
quotations and returns "these 14 drafts would change, total tax +₹3,240". Issued documents are
listed as *unaffected* (they are frozen). This makes editing tax config safe for non-developers.

---

## 4. What changes when the law or the business changes

The test of the design: every row below must be possible **without a code change** except where marked.

| Scenario | Layer | What someone does | Code change? |
|---|---|---|---|
| GST slab changes (like GST 2.0) | L2→L3 | Ship pack v2 with new rates dated from the notification date; admin reviews diff and applies | No |
| A category moves from 12% to 5% | L3 | Close old category mapping, add new one dated | No |
| New cess / levy on some goods | L3 | Add component + rate + rule output | No |
| TDS sections renumbered (like Apr 2026) | L2→L3 | New `withholding_sections` rows dated, with `aliases` to old numbers | No |
| TDS rate or threshold changes | L3 | Close the row, add a new dated row | No |
| Customer gets a lower-deduction certificate | L3 | Add certificate to customer tax profile | No |
| E-invoice threshold lowered | L3 | Toggle `e_invoice_applicable` on the registration (or pack updates the default threshold) | No |
| Company registers in a new state | Identity | Add a tax registration (GSTIN); series auto-created per FY | No |
| New FY starts | L1 mechanism | Series rows created on first issue for the new FY from the format template | No |
| Change invoice number format | L3 | Edit the series format template (only for future series) | No |
| Company decides to bill everything upfront | L4 | `billing_mode = full_upfront` | No |
| Company wants proformas before invoices | L4 | `proforma_enabled = true` | No |
| Rounding to nearest ₹1 turned on/off | L3 regime setting | Edit regime rounding | No |
| Approval needed above ₹5 lakh | L4 | `invoice_approval_threshold` | No |
| A new country (UAE VAT) | L2 | New pack | No (unless it needs a new *condition kind*) |
| US sales tax (thousands of rates) | L6 | Enable external provider adapter for that regime | Adapter once |
| New GSP for e-invoicing | L6 | New adapter class | Adapter once |
| Export to Zoho instead of Tally | L6 | New export adapter | Adapter once |
| New billing trigger (e.g. usage-based) | L1 | New schedule strategy in the registry | **Yes** (small, isolated) |
| New legal document type (e.g. self-invoice for RCM) | L1 | New doc type + lifecycle | **Yes** |

---

## 5. Package layout inside 02_revenue

Follows the service's existing `models/ schemas/ services/ routes/` structure; the finance code is
grouped so it can be lifted out later.

```
src/v1/02_revenue/
├── finance/
│   ├── money.py                 # Decimal helpers, Money type, quantize per currency
│   ├── tax/
│   │   ├── engine.py            # pure: calculate(TaxContext) -> TaxResult   (no I/O)
│   │   ├── context.py           # TaxContext, PartyProfile, LineInput dataclasses
│   │   ├── result.py            # TaxResult, TaxLine, Withholding, Explanation
│   │   ├── conditions.py        # typed condition vocabulary + matcher
│   │   ├── supply_type.py       # intra/inter/export/sez/b2c resolution (uses config, not constants)
│   │   ├── rounding.py          # rounding modes from regime config
│   │   ├── loader.py            # DB -> ConfigSnapshot as of a date (cached by org + revision)
│   │   └── providers/           # internal (rules) + external adapters (registry, §9)
│   ├── packs/
│   │   ├── in_gst.v1.yaml       # India GST pack (components, rates, categories, rules, states)
│   │   ├── in_itd.v1.yaml       # India income-tax withholding pack (sections + aliases)
│   │   ├── schema.py            # Pydantic schema the packs are validated against
│   │   └── applier.py           # diff + apply a pack version into an org's config
│   ├── numbering.py             # series lookup/creation, locked increment, format rendering
│   ├── billing/
│   │   ├── schedule_strategies.py  # percent / fixed / milestone / recurring (registry)
│   │   └── scheduler.py         # contract -> schedule lines; ready lines -> draft invoices
│   ├── receivables/
│   │   ├── allocation.py        # payment -> invoices with cash/tds/gst_tds/write-off
│   │   └── tds.py               # TDS receivable lifecycle + 26AS matching
│   ├── policies.py              # reads finance_settings; one function per decision
│   └── adapters/                # e-invoice, accounting export, gstin lookup (interfaces + stubs)
├── models/      # + tax_config.py, tax_profile.py, finance_settings.py, document_tax.py, receivables.py
├── schemas/     # + tax.py, finance_settings.py, receivables.py
├── services/    # invoice_service / quotation_service / payment_service call finance/*, no tax maths inside
└── routes/      # + tax.py, finance_settings.py, billing_schedules.py, receipt_vouchers.py, tds_receivables.py
```

Rules for this package:

- `finance/tax/engine.py` imports nothing from SQLAlchemy, FastAPI or `models/`. It takes a config
  snapshot and inputs and returns a result. Exhaustively unit-testable.
- `quotation_service` and `invoice_service` **delete their own calculators** (`calculate_tax_and_totals`,
  `calculate_invoice_lines`) and call one `finance.tax` entry point (fixes D11).
- Services ask `policies.py` questions ("is proforma enabled for this org?"), never read settings columns directly — so a policy can later become more complex without touching callers.

---

## 6. Data model

### 6.1 Adopted from the billing plan unchanged

| Table | Billing plan § |
|---|---|
| `tax_regimes`, `tax_components`, `tax_rates`, `tax_categories`, `tax_rules`, `withholding_sections` | §7.1–7.6 |
| Client tax profile fields, lower-deduction certificates | §8.2 |
| Offering → `tax_category_id`, `classification_code`, `price_includes_tax` | §8.3 |
| `document_line_taxes` + document tax header fields | §10.1 |
| Payment allocation settlement fields, `tds_receivables` | §11.2–11.3 |

### 6.2 Added by this plan (for flexibility)

**`tax_jurisdictions`** — states/UTs and their codes as data, not constants.

| Column | Notes |
|---|---|
| regime_id, code | `29`, `27`, `04` … (GST state codes) |
| name | Karnataka, Maharashtra, Chandigarh |
| kind | `state`, `ut_with_legislature`, `ut_without_legislature`, `country` |
| effective_from / to | states and codes do change (e.g. UT mergers) |

The UT-vs-state rule (CGST+UTGST) reads `kind` from this table instead of a hardcoded list.

**`config_revisions`** — one row per change set: `organization_id`, `revision`, `changed_by`,
`changed_at`, `source` (`manual` | `pack:in_gst@2`), `summary`. Mirrors to the insight audit log.

**`pack_applications`** — which pack version an org has applied: `pack_code`, `version`, `applied_at`,
`applied_by`, `diff_summary`. Lets us tell admins "India GST pack v3 is available".

**`document_series`** (evolves today's `invoice_series`, keeps the table name to avoid churn):

| Column | Notes |
|---|---|
| organization_id, registration_id | per GSTIN |
| doc_type | `tax_invoice`, `credit_note`, `debit_note`, `proforma`, `receipt_voucher`, `payment_receipt`, `refund_voucher` |
| fiscal_year | computed from org `fiscal_year_start`, e.g. `2026-27` |
| format | template, e.g. `{prefix}/{fy_short}/{seq:05}` → `INV/26-27/00042` |
| prefix | `INV`, `CN`, `RV`… |
| next_number | locked increment (`SELECT … FOR UPDATE`) |
| max_length | `16` from the regime config (GST Rule 46); validated on render |
| allowed_chars | regex from the regime config |
| status | `active` / `closed` |

New FY → series row auto-created from the org's **series template** (`series_templates` table: per doc
type, default format and prefix). Nothing about "26-27" is in code.

**`compliance_deadlines`** (L3, from packs) — data for warnings and reminders:

| Column | Example |
|---|---|
| code | `GST_CREDIT_NOTE_LIMIT`, `GST_INVOICE_WINDOW_SERVICES`, `EINV_REPORTING_LIMIT`, `ITC_PAYMENT_LIMIT`, `TDS_DEPOSIT` |
| rule | JSON: `{"type":"after_fy_end","month":11,"day":30}`, `{"type":"days_after","field":"supply_date","days":30}`, `{"type":"days_after","field":"issue_date","days":180}` |
| severity | `warn` / `block` (policy can downgrade a block to warn-with-reason) |
| effective_from / to | |

The 30-Nov credit-note limit, the 30-day invoicing window, the 30-day e-invoice limit and the 180-day
ITC clock (research §7.7) are rows here, not `if` statements.

**`ledger_accounts`** + **`ledger_mappings`** (L3): every component, withholding section, and money
event (receivable, bank, round-off, write-off, bank charges, advance) maps to an account code. The
accounting export reads mappings; changing the chart of accounts is config.

**Documents — new types and records** (sales side):

| Record | Purpose |
|---|---|
| `invoices.doc_type` gains `debit_note`, `receipt_voucher`, `refund_voucher` | same table, same tax-line storage, own series |
| `invoices.tax_point_date`, `supply_type`, `round_off`, `config_revision`, `schedule_line_id` (unique) | engine inputs/outputs frozen |
| `advance_adjustments` | receipt voucher ↔ tax invoice, amount and tax adjusted |
| `write_offs` | accounting-only reduction of `balance_due` with reason and approver — never a credit note |

Money columns move to `Numeric(18,2)` with `Mapped[Decimal]` as each table is touched.

### 6.3 Supplier registrations (identity)

Extend identity `tax_registrations` (billing plan §8.1): `state_code` (derived from GSTIN),
`registration_type`, `lut_number/valid_from/valid_to`, `e_invoice_applicable`,
`e_invoice_reporting_limit_days`, `valid_to`. Add identity routes and an **internal read endpoint**
`GET /internal/tax-registrations?organization_id=…&as_of=…`. Revenue caches the result per org
(short TTL) and **stores the snapshot on every issued document**, so identity being down never
breaks an already-issued invoice.

---

## 7. Policy settings

One row per organization, copied from the `DeliverySettings` pattern: **no row = defaults**, every
behaviour change ships behind a setting, each column documented with what it does and the migration
that added it.

```text
finance_settings  (PK organization_id)
  billing_mode                 enum   staged | full_upfront | manual            default: staged
  proforma_enabled             bool   default false
  receipt_voucher_on_advance   bool   default true   (services; legal requirement where GST applies)
  invoice_requires_schedule    bool   default true   (invoice only from a schedule line, else ad-hoc with reason)
  invoice_approval_threshold   Decimal? default null (above → approval request in 04_control)
  credit_note_deadline_mode    enum   block | warn_with_reason   default block
  allow_rate_override          bool   default false  (L5 override of a computed rate, with reason)
  tds_expectation_mode         enum   per_payment | on_invoice   default per_payment
  collections_on_net           bool   default true   (dunning on balance − expected TDS)
  write_off_tolerance          Decimal default 0     (auto-suggest write-off for short-pays under this)
  auto_draft_from_schedule     bool   default false  (job drafts invoices when lines fall due)
  default_payment_terms_days   int    default 30
  version, updated_by, updated_at
```

`finance/policies.py` exposes one function per decision, for example
`may_issue_without_schedule(settings, payload)`, `credit_note_deadline_action(settings, deadline)` —
so the meaning of a setting is in one place.

---

## 8. Packs

### 8.1 Format

Packs are code-reviewed YAML validated by `packs/schema.py`. Example (trimmed):

```yaml
pack: in_gst
version: 2
regime: { code: IN-GST, country: IN, kind: indirect, rounding_mode: half_up,
          rounding_level: line, document_round_off: nearest_1 }
series_rules: { max_length: 16, allowed_chars: "^[A-Za-z0-9/-]+$" }

components:
  - { code: CGST,  label: "Central GST",   behaviour: added, sequence: 10 }
  - { code: SGST,  label: "State GST",     behaviour: added, sequence: 10 }
  - { code: UTGST, label: "UT GST",        behaviour: added, sequence: 10 }
  - { code: IGST,  label: "Integrated GST", behaviour: added, sequence: 10 }

rates:
  - { code: GST_18, component: IGST, percent: 18, effective_from: 2017-07-01,
      notification: "Notf 1/2017-IT(R)" }
  - { code: GST_12, component: IGST, percent: 12, effective_from: 2017-07-01,
      effective_to: 2025-09-22, notification: "GST 2.0" }
  - { code: GST_5,  component: IGST, percent: 5,  effective_from: 2017-07-01 }
  - { code: GST_40, component: IGST, percent: 40, effective_from: 2025-09-22 }

categories:
  - { code: SVC_18, name: "Services 18%", treatment: taxable, rate: GST_18, classification: "9983" }
  - { code: ZERO_RATED, name: "Zero-rated", treatment: zero_rated }

rules:
  - priority: 40
    when: { supply_type: [intra_state], jurisdiction_kind: [state, ut_with_legislature] }
    then: [ { component: CGST, rate_from_category: true, split: 0.5 },
            { component: SGST, rate_from_category: true, split: 0.5 } ]
  - priority: 40
    when: { supply_type: [inter_state] }
    then: [ { component: IGST, rate_from_category: true } ]
  - priority: 80
    when: { supply_type: [export, sez], lut_valid: true }
    then: [ { component: IGST, percent: 0 } ]
    note: "Supply meant for export under LUT without payment of IGST"

jurisdictions:
  - { code: "29", name: Karnataka, kind: state }
  - { code: "04", name: Chandigarh, kind: ut_without_legislature }
  # … all states/UTs

deadlines:
  - { code: GST_CREDIT_NOTE_LIMIT, rule: { type: after_fy_end, month: 11, day: 30 }, severity: block }
  - { code: GST_INVOICE_WINDOW_SERVICES, rule: { type: days_after, field: supply_date, days: 30 }, severity: warn }
```

The rate is defined **once** (`GST_18`) and split by the rule (`split: 0.5`), so a slab change
touches one row, not three.

`in_itd` carries `withholding_sections` with `payment_code`, `aliases: ["194J"]`, rates by deductee
type, thresholds, and dates — the old-Act rows end `2026-04-01`, the new-Act rows start then.

### 8.2 Lifecycle

```
Developer/CA updates YAML → PR review → deploy
        ▼
Org admin sees "India GST pack v3 available"
        ▼
GET /tax/packs/in_gst/versions/3/diff   → added / closed / changed rows + impact preview (§3.4)
        ▼
POST /tax/pack-applications {pack: in_gst, version: 3}   → rows inserted/closed, config_revision++
```

- **Never auto-apply** by default (open decision 8 in the billing plan → recommended: review required;
  a policy flag `auto_apply_packs` can be added later).
- An org that has **edited** a row keeps its edit; the diff shows the conflict and the admin chooses.
- New orgs get the latest pack versions on bootstrap (lazy: first time the finance module is used,
  like document categories).

### 8.3 Who keeps packs correct

Rates in packs must be verified by a CA before release (research doc confidence markers). Each rate
row carries `notification` — the government reference — so a reviewer can check it.

---

## 9. Extension points

Each is a small interface + registry keyed by a config value, with a stub implementation for tests
and sandbox. Selecting the implementation is config (L3/L4); adding a new one is a contained code change.

| Interface | Selected by | Implementations (first) |
|---|---|---|
| `TaxProvider.calculate(ctx) -> TaxResult` | `tax_regimes.provider` | `internal` (rules engine); later `avalara`, `stripe_tax` |
| `ScheduleStrategy.lines(contract, term) -> [ScheduleLine]` | `contract_payment_terms.trigger_type` | `advance_percent`, `fixed_amount`, `milestone`, `on_completion`, `recurring` |
| `EInvoiceProvider.generate/cancel` | registration setting `e_invoice_provider` | `sandbox_stub`; later a GSP |
| `AccountingExporter.export(journal)` | org setting `accounting_target` | `csv`; later `tally_xml`, `zoho_books` |
| `GstinValidator.validate(gstin)` | regime | `checksum` (offline); later `portal_lookup` |
| `TdsStatementParser.parse(file)` | upload type | `26as_text`, `ais_csv` |
| `SeriesFormatter.render(template, ctx)` | — | one implementation; tokens `{prefix} {fy} {fy_short} {seq:N} {reg_state}` |

New `trigger_type` values in `ContractPaymentTerm` map to strategies; an unknown value is a
validation error at contract creation, not a silent skip.

---

## 10. Flows mapped to code

### 10.1 Configure (once per org)

```
Identity: legal entity + tax registration(s) (GSTIN, state, LUT, e-invoice flags)
Revenue:  first finance use → apply latest packs → series templates → finance_settings defaults
Offerings: pick tax category (+ SAC override)
Clients:   tax profile (registration type, GSTIN, place of supply, TDS section, certificates)
```

### 10.2 Quote → contract → schedule (research §7.8)

```
Quotation draft ── finance.tax.calculate (preview, not frozen)
   │ sent → snapshot frozen (config_revision stored)
   ▼
Contract activated ── scheduler.generate(contract)
   for each ContractPaymentTerm: ScheduleStrategy[trigger_type].lines(...)
   → billing_schedule_lines (status: planned)
   │
   ▼  line due (date reached / milestone event from 03_delivery / user "bill now")
line → ready ── policies.billing_mode == staged ?
   ├─ auto_draft_from_schedule → draft invoice created by the job
   └─ else → appears in "ready to bill" list
```

### 10.3 Issue an invoice (one transaction)

1. Load registration snapshot as of the issue date (identity, cached) → error `SUPPLIER_REGISTRATION_REQUIRED` if none.
2. `policies.may_issue(...)`: schedule line required? approval threshold? → `APPROVAL_REQUIRED` via 04_control.
3. `finance.tax.calculate(ctx)` with `tax_point_date` → freeze `document_line_taxes`, header fields, `config_revision`.
4. Deadlines (`compliance_deadlines`): e.g. invoicing window passed → warn/block per severity and policy.
5. `numbering.next(registration, doc_type, fy)` with row lock; render format; validate length/chars.
6. Snapshot client + supplier; status `issued`; mark schedule line `invoiced`.
7. Outbox event `revenue.invoice.issued.v1` → PDF (05_documents), e-invoice job (adapter), email (06_communication).

### 10.4 Payment

```
POST /payments {amount, allocations:[{invoice_id, cash, tds:{section, amount}, gst_tds, write_off}]}
  receivables.allocation:
    validate cash ≤ receipt − charges; TDS vs expected (warn on rate mismatch)
    invoice.amount_settled += cash + tds + gst_tds + write_off → status partially_paid / paid
    tds_receivables row per TDS amount (status expected)
  unallocated remainder → customer advance
    └─ policies.receipt_voucher_on_advance → receipt voucher (tax computed by the engine)
```

### 10.5 Corrections

| Need | Document | Rule source |
|---|---|---|
| Price too high / deficiency / cancellation | Credit note — copies original tax lines (never re-derived) | Deadline from `compliance_deadlines`; `credit_note_deadline_mode` policy |
| Price too low / extra charges | Debit note | Same |
| Client won't pay the rest | `write_offs` record — no GST effect | Approval via 04_control above threshold |
| Advance refunded | Refund voucher | Engine on the original receipt voucher |

### 10.6 What the finance team sees

- **Ready to bill** (schedule lines due), **Drafts**, **Issued/overdue**.
- **GST issued vs cash collected** per month (research §7.7).
- **TDS receivable** by customer/quarter, unmatched against 26AS.
- **Deadlines**: credit-note limit approaching, invoicing window, client's 180-day ITC date.

---

## 11. Other services

| Service | What changes | Contract |
|---|---|---|
| **01_identity** | Routes for legal entities + tax registrations; extra registration fields; internal read endpoint; new permission codes in `permission_catalog.py`; `fiscal_year_start` already exists and is used for FY | Revenue never trusts headers; reads via `identity_client` |
| **03_delivery** | Emits `work.milestone.completed` → schedule line becomes `ready` | Event; delivery knows nothing about money |
| **04_control** | Approval requests for invoices above threshold, write-offs, credit-note deadline overrides | Existing approval API |
| **05_documents** | Invoice PDFs, signed e-invoice JSON, TDS certificates, 26AS uploads as attachments (`subject_type=invoice/tds_receivable`) | Generic subject-linked attachments |
| **06_communication** | Invoice emails, payment reminders, deadline reminders | Notification client (exists) |
| **08_insight** | Audit of config changes (`config_revisions`), finance dashboards | Events |
| **09_assets** | Vendor accounts — the future purchase side reads vendor tax profiles from the same `finance` model | Later phase |

Events go through an outbox (as delivery does for task notifications), so a failing downstream service
never rolls back an issued invoice.

---

## 12. API

Base `/api/revenue/v1`. Endpoints from billing plan §14 are adopted. Added by this plan:

| Method | Path | Purpose |
|---|---|---|
| GET / PATCH | `/finance-settings` | Org policy (§7); `If-Match` |
| GET | `/tax/config?as_of=YYYY-MM-DD` | Effective config on a date (all tables) |
| GET | `/tax/config-revisions` | Change history |
| GET | `/tax/jurisdictions` | States/UTs |
| GET | `/tax/packs` | Available packs, versions, applied version |
| GET | `/tax/packs/{code}/versions/{v}/diff` | What applying would change + impact preview |
| POST | `/tax/pack-applications` | Apply a pack version |
| POST | `/tax/config-previews` | Proposed config edit → affected drafts/quotations |
| GET / POST / PATCH | `/tax/deadlines` | Compliance deadline rows |
| GET / POST / PATCH | `/document-series`, `/series-templates` | Numbering formats |
| GET / POST / PATCH | `/ledger-accounts`, `/ledger-mappings` | Chart of accounts mapping |
| POST | `/billing-schedules/{id}/lines/{line_id}/invoices` | Bill a line now |
| GET | `/billing-schedule-lines?status=ready` | Ready-to-bill list |
| POST | `/receipt-vouchers`, `/receipt-vouchers/{id}/adjustments` | Advance + adjustment |
| POST | `/invoices/{id}/write-offs` | Accounting write-off |
| GET | `/reports/gst-vs-cash?period=2026-09` | GST liability vs collection |

All writes take `Idempotency-Key`; updates take `If-Match`; errors keep the `{detail: {code, message}}` shape.

---

## 13. Permissions

Added to identity's catalog with the routes, per `.agents/AGENT_PERMISSIONS.md` (every route guarded
by `require_permission`, tests that none is unguarded):

| Code | Meaning |
|---|---|
| `revenue.tax.read` | View tax configuration, packs, deadlines, jurisdictions |
| `revenue.tax.manage` | Edit tax configuration, apply packs |
| `revenue.finance_settings.read` / `.write` | View / change finance policy |
| `revenue.tax_profile.write` | Edit customer tax profiles and certificates |
| `revenue.series.manage` | Edit numbering formats |
| `revenue.invoice.issue` | Issue (separate from `revenue.invoice.write` = draft) |
| `revenue.credit_note.issue` | Issue credit/debit notes |
| `revenue.write_off.create` | Write off balances |
| `revenue.billing_schedule.read` / `.write` | View / bill schedule lines |
| `revenue.tds.reconcile` | Import 26AS, match TDS |
| `revenue.ledger.manage` | Edit ledger accounts and mappings |
| `revenue.report.tax` | Tax and GST reports |

Per the user-based access model, these are individual permissions; a "Finance admin" role is only a preset.

---

## 14. Guardrails against hardcoding

1. **No-literals test** (`tests/test_no_tax_literals.py`): scans `finance/` and the billing services for
   GSTIN patterns, two-digit state codes in string literals, known rate literals (`18`, `9.0`, `0.18`…)
   next to tax words, FY strings like `"26-27"`, and section numbers like `"194J"`. Allowed only in
   `finance/packs/*.yaml` and tests. Fails CI otherwise.
2. **Engine refuses to guess**: no rule → `TAX_RULE_NOT_FOUND`; no rate effective → `TAX_RATE_NOT_EFFECTIVE`;
   never a silent 0% or 18%.
3. **Pack schema validation** in CI: every pack version loads, has no overlapping dates, every rule
   output references an existing component/rate, every jurisdiction kind is known.
4. **Effective-date boundary tests** for every dated row in the packs (day before / day of).
5. **Settings default test**: an org with no `finance_settings` row behaves exactly as documented defaults.
6. **Issued documents immutable test**: changing config and re-reading an issued invoice returns identical totals.

---

## 15. Migration and compatibility

Billing plan §17 is adopted. Additions:

1. **Settings**: no rows created; defaults apply (staged billing, receipt vouchers on).
2. **Packs**: on first use per org, apply `in_gst` and `in_itd` latest; record `pack_applications`.
3. **Hardcoded supplier**: migration does **not** create a registration from `"29AABCF9876L1Z3"`.
   Existing invoices keep their stored `supplier_gstin`. New issues require a real registration
   (`SUPPLIER_REGISTRATION_REQUIRED`) — surfaced in the UI as a setup step.
4. **Series**: `invoice_series` rows created per (registration, doc type, FY) with `next_number` =
   max existing + 1, parsed from today's `invoice_no` values.
5. **Payments**: today's single `tds_amount` moved onto allocations and into `tds_receivables` as `expected`.
6. **API**: `cgst_total/sgst_total/igst_total` and line `cgst/sgst/igst_amount` remain in responses,
   computed from tax lines; new `taxes[]`, `withholding[]`, `net_receivable`, `supply_type` added.
   Old columns dropped one release after the frontend switches.
7. Alembic migrations in `02_revenue/migrations` and `01_identity/migrations`, reversible where data
   allows. Remember identity's `.env` points at the shared remote DB — run identity migrations
   deliberately.

---

## 16. Phases and PR-sized steps

Each step is one reviewable PR with its tests and permissions.

### Phase 0 — Foundation (no behaviour change)
1. `finance/money.py`; switch revenue money columns' Python types to `Decimal` (schema already `Numeric`).
2. `finance_settings` model + migration + `GET/PATCH /finance-settings` + permissions.
3. Identity: tax registration fields + routes + internal read endpoint + revenue `identity_client` method.

### Phase 1 — Config + engine
4. Tax config models (regimes, components, rates, categories, rules, jurisdictions, sections, revisions, pack applications) + migration.
5. Pack schema + `in_gst.v1.yaml` + `in_itd.v1.yaml` + applier + CI pack validation.
6. Pure engine + exhaustive table tests (billing plan §18 list + boundary dates).
7. Loader (as-of snapshot, cached by org+revision) + `POST /tax/calculations` + config read routes.
8. Config write routes with effective-date guards + impact preview.

### Phase 2 — Documents on the engine
9. `document_line_taxes` + header fields; quotations use the engine; delete the quotation calculator.
10. Invoices use the engine; delete the invoice calculator; supplier from registration (removes D1, D2, D6, D7, D11).
11. Numbering via `invoice_series` + series templates + FY from org settings (removes D5).
12. Credit/debit notes copy original tax; deadline from `compliance_deadlines`; never set paid (removes D3, D4).
13. Data migration of existing documents + compatibility fields; no-literals test turned on.

### Phase 3 — Staged billing (research §7.8)
14. Schedule strategies + scheduler: contract activation generates lines.
15. Ready-to-bill list, "bill now", optional auto-draft job.
16. Delivery milestone event → line ready.
17. Receipt vouchers + advance adjustments.
18. Optional proforma flow.

### Phase 4 — Receivables
19. Per-allocation TDS / GST-TDS / write-off; payment receipts numbered via series (removes D9).
20. `tds_receivables` + 26AS import + matching.
21. Write-offs with approval; collections on net expected; GST-vs-cash report.

### Phase 5 — Compliance and books
22. Ledger accounts/mappings + journal builder + CSV export adapter.
23. E-invoice adapter interface + sandbox stub + 30-day warnings.
24. GSTR-1 data export.

### Phase 6 — Later
25. Purchase side: vendor tax profiles (with 09_assets), vendor bills, TDS we deduct, RCM, ITC register.
26. Second country pack (proves no engine changes).
27. External tax provider adapter.

Frontend (clientadmin) follows each phase (billing plan §16) plus: finance settings page, pack upgrade
diff screen, config history, ready-to-bill list, GST-vs-cash card.

---

## 17. Testing

Billing plan §18 is adopted. Additions:

- **Policy matrix**: each `finance_settings` flag on/off for the flows it touches.
- **Pack upgrade**: apply v1, edit a row, apply v2 → conflict shown, org edit preserved unless chosen.
- **As-of reads**: `/tax/config?as_of` before and after a pack change.
- **Scheduler**: 50/50 terms, milestone terms, recurring monthly; a line never billed twice (unique `schedule_line_id`); unknown `trigger_type` rejected.
- **Partial payment**: research §7.8 timeline reproduced as an integration test (GST on each invoice, receipts, balances, TDS receivables).
- **No-literals test** and **immutable issued documents** (§14).

---

## 18. Open decisions

Recommended answer first; the user decides.

| # | Question | Recommendation |
|---|---|---|
| 1 | Billing stays under `/api/revenue/v1` with `revenue.*` codes, or moves to the spec's `/api/billing/v1`? | Stay in revenue now; the `finance/` boundary makes a later split cheap |
| 2 | Supplier registrations owned by identity (with an internal read) or copied in revenue? | Identity owns; revenue caches and snapshots on documents |
| 3 | Pack upgrades auto-applied or reviewed? | Reviewed (diff + impact preview) |
| 4 | Default `billing_mode` for existing orgs? | `staged`, with `full_upfront` available |
| 5 | Credit-note deadline: block or warn? | Block, with `warn_with_reason` as an org policy |
| 6 | Allow manual rate override on a document? | Off by default; on only with reason + permission |
| 7 | Does purchase side (vendor bills/TDS we deduct) also go in 02, or a future finance service? | Same `finance/` package in 02 for now; revisit when payroll arrives |
| 8 | Who signs off pack rates before release? | The company's CA, per pack version |
| 9 | First e-invoice GSP? | Undecided; ship interface + sandbox stub |


---

## 19. Build status (2026-10-09)

### 19.1 Built

| Phase | What exists now | Where |
|---|---|---|
| 0 Foundation | Decimal money helpers; `finance_settings` (one row per org, defaults without a row); the org's own tax registrations with GSTIN checksum + jurisdiction from the number | `finance/money.py`, `models/finance_settings.py`, `models/tax_registration.py`, `routes/finance_settings.py`, `routes/tax_registrations.py` |
| 1 Config + engine | Dated `tax_config_entries` (9 kinds, strict schema per kind), revisions, pack applications; packs `core`, `in_gst`, `in_itd` (YAML); pack diff/apply with local-edit conflicts; pure engine; lint of references; overlap checks; supersede-in-one-step; calculation preview | `finance/tax/*`, `finance/packs/*`, `routes/tax.py`, `services/tax_config_service.py` |
| 2 Documents | Quotations, invoices, credit and debit notes on the engine; frozen `document_tax_lines`; numbering from series templates (per registration, FY from the regime); credit notes copy the original's treatment, have a deadline from config, never mark paid; write-offs | `services/invoice_service.py`, `services/quotation_service.py`, `finance/numbering.py`, `finance/receivables/settlement.py` |
| 3 Staged billing | Contract activation builds the schedule from payment terms (strategy per trigger type; billing mode setting); ready-to-bill list; mark milestone ready; bill a line → draft invoice; contracts with a schedule refuse ad-hoc invoices (setting) | `finance/billing/strategies.py`, `services/billing_schedule_service.py`, `routes/billing_schedules.py` |
| 4 Receivables | Per-allocation TDS / GST-TDS; TDS receivables with reconciliation status; payment receipts from the series; collections chase net of expected TDS (setting); GST-vs-cash report | `services/payment_service.py`, `services/receivables_service.py`, `routes/receivables.py`, `services/collection_service.py` |
| Cross-cutting | 7 new permission codes in identity's catalog; route-guard test; no-tax-literals test; migration `a3f1c7d9e2b4` with data backfill (verified upgrade → downgrade → upgrade on MySQL 8, `alembic check` clean) | `permissions.py`, `tests/`, `migrations/versions/20261009_1800_a3f1c7d9e2b4_finance_tax_foundation.py` |

Tests: revenue 143 passing (was 64), identity 119 passing.

### 19.2 Decisions (all open decisions resolved)

| # | Decision | Why |
|---|---|---|
| 1 | Billing stays at `/api/revenue/v1` with `revenue.*` codes | No client breaks; the `finance/` package boundary keeps a later move to a billing service cheap. |
| 2 | **Changed from the plan:** the organization's tax registrations live in revenue (`org_tax_registrations`), not identity | Every reader is billing; no network call to issue an invoice; it moves with billing if billing becomes a service; identity's `legal_entities`/`tax_registrations` tables were empty with no routes, and changing identity means migrating the shared remote database. Documents still snapshot the registration. |
| 3 | **Changed from the plan:** one `tax_config_entries` table (kind, code, dates, validated JSON) instead of a table per kind | One API, one change history, one pack applier, one as-of query for every kind; a new kind is a schema class, not a table + routes + migration. Validation is strict per kind, so invalid data is still refused at write. |
| 4 | Pack upgrades are reviewed (diff, then apply); only the first use of an organization applies the default packs automatically | Tax changes must be seen by a person; entries an org edited are never overwritten without being named in `overwrite`. |
| 5 | Default billing mode `staged`; `full_upfront` and `manual` available | GST follows the invoice; staging keeps GST close to cash (research §7.7–7.8). |
| 6 | Credit-note deadline blocks by default; `warn_with_reason` allows it with a stored reason | The law blocks; the org (with its CA) can choose to record exceptions. |
| 7 | Manual rate override on a document: not built | Off by default in the plan; nothing needs it yet, and it is the easiest way to get tax wrong. |
| 8 | Purchase side goes into the same `finance/` package later | Config model already covers it (sections, deductee types, RCM categories). |
| 9 | E-invoice GSP: not chosen; nothing built yet | Phase 5. |
| 10 | Invoice numbers are unique per supplier registration (GSTIN), not per organization | GST rules require uniqueness per GSTIN per FY; an org with two GSTINs runs two series. A `{jurisdiction}` token is available for orgs that want distinct-looking numbers. |
| 11 | The TDS deductee is the organization: its type is a finance setting, its PAN comes from its registration; lower-deduction certificates stay on the customer profile | The customer deducts from us, so our type and PAN decide the rate; a certificate names the deductor it covers. |
| 12 | A payment term's `due_offset_days` sets the drafted invoice's payment due date, not when the line is billed | That is what the existing contract schema means by it (default 15 days to pay). |
| 13 | A bare GST rate (older clients, `gst_rate`) maps to the plain category with that rate: never a reverse-charge one; the default category wins ties | Found by a failing test: 18% was mapping to legal services under RCM. |

### 19.3 Not built yet

- Receipt vouchers for advances and the proforma step (phase 3 steps 17–18).
- 26AS / AIS import and auto-matching (statuses can be set by hand).
- Impact preview of a config change on open drafts (§3.4); lint + overlap + in-effect guards are in place.
- Approval through 04_control for large invoices / write-offs; delivery milestone events → schedule line ready (manual PATCH for now).
- Phase 5: ledger mapping and accounting export, e-invoice adapter, GSTR-1 export, compliance reminders.
- Phase 6: purchase side, a second country pack, external tax provider.
- Frontend: done in clientadmin (2026-10-09), see §19.5.

### 19.4 Before deploying

1. Have a CA confirm the pack rates, sections and dates (`finance/packs/*.yaml`).
2. Each organization must add its GSTIN (`POST /tax-registrations`) before billing (`SUPPLIER_REGISTRATION_REQUIRED` otherwise). Existing invoices keep their stored supplier GSTIN.
3. Orgs that want their old prefix (e.g. `FTB`) supersede the `tax_invoice` series template before their first new invoice of the year; the new series continues after the highest existing number in that format issued under the same GSTIN. (Existing invoices carry the old hardcoded GSTIN, so a real GSTIN starts its own count.)
4. Identity must restart to add the new permission codes; revenue's migration must run. Both `.env` files point at the shared remote database, so this needs agreement with the team.
5. `pyyaml` is a new revenue dependency (requirements.txt).

### 19.5 Frontend (clientadmin, 2026-10-09)

- **Tax setup** page (`/tax-setup`, `revenue.tax.read`; edits need `revenue.tax.manage`): registrations (GSTIN, LUT, default), billing settings, rates & rules (any kind, by date; close, replace from a date, delete future entries, add with a JSON form the backend validates), packs (review the diff, choose conflicts to overwrite, apply), history.
- **Tax reports** page (`/tax-reports`): GST vs cash by month; TDS withheld with reconciliation status and certificate number.
- **Ready to bill** page (`/billing-schedules`): billable lines across contracts; per contract (`?contract=`): mark milestone reached, bill early, cancel, draft the invoice.
- Invoices: generic tax totals, per-line taxes, expected TDS and cash, notes, deadlines, credited / written off; whole or per-line credit notes (with the deadline override reason when allowed), debit notes, write-offs. New invoice: tax category per line (no 18% / SAC defaults).
- Payments: cash and TDS withheld per invoice; debit notes payable.
- Quotations: generic tax totals and notes. Offerings: tax category instead of a GST %. Contracts: link to the billing schedule. Customers: a Tax tab (customer type, place of supply, TDS section, lower deduction certificates, and what billing will use).
- `ACCESS` rules, access-editor labels and `FRIENDLY` copy for the new codes. Verified with `npm run lint && npm run build` (clientadmin and superadmin); not clicked through in a browser.

### 19.6 Migration order with PR #50 (2026-10-09)

PR #50 (`gkr`, "Finished sales tasks logged on revenue's timelines") adds revenue migration
`a7d3c9e1f5b2` on the same parent (`d965483ea424`) the finance migration had, which would leave two
Alembic heads. The finance migration now revises `a7d3c9e1f5b2` (chain: `d965483ea424 →
a7d3c9e1f5b2 → a3f1c7d9e2b4`), checked on main + PR #50 + this work: one head, upgrade → downgrade
→ upgrade on MySQL 8, `alembic check` clean, revenue tests 146 passing. Merge `main` (with PR #50)
into this branch before committing the finance work, or its migration points at a revision the
branch doesn't have.

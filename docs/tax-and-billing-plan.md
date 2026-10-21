# Tax & Billing — Research and Build Plan

> Status: **plan only, nothing built yet.** Written 2026-10-05.
> Scope: a configurable tax engine plus the full quote-to-cash flow (quotation → contract →
> billing schedule → proforma → tax invoice → credit/debit note → payment & TDS → collections →
> reconciliation → accounting export / returns). India (GST + TDS) first; the model must take
> other countries as configuration, not code.

---

## Table of contents

1. [Goals](#1-goals)
2. [Research: how a real company's quote-to-cash works](#2-research-how-a-real-companys-quote-to-cash-works)
3. [Research: tax rules that shape the design](#3-research-tax-rules-that-shape-the-design)
4. [Research: how tax engines are modelled elsewhere](#4-research-how-tax-engines-are-modelled-elsewhere)
5. [What exists in FBOS today (and what's wrong)](#5-what-exists-in-fbos-today-and-whats-wrong)
6. [Design principles](#6-design-principles)
7. [Data model — tax configuration](#7-data-model--tax-configuration)
8. [Data model — party tax profiles](#8-data-model--party-tax-profiles)
9. [The tax engine](#9-the-tax-engine)
10. [Documents: quotation, proforma, invoice, credit/debit note](#10-documents)
11. [Payments, TDS and receivables](#11-payments-tds-and-receivables)
12. [Accounting, returns and reports](#12-accounting-returns-and-reports)
13. [Beyond India](#13-beyond-india)
14. [API surface](#14-api-surface)
15. [Permissions](#15-permissions)
16. [Frontend](#16-frontend)
17. [Migration from the current schema](#17-migration-from-the-current-schema)
18. [Testing strategy](#18-testing-strategy)
19. [Phased delivery](#19-phased-delivery)
20. [Open decisions](#20-open-decisions)
21. [Worked examples](#21-worked-examples)
22. [Glossary](#22-glossary)
23. [Sources](#23-sources)

---

## 1. Goals

- **Every tax is configuration.** Components (CGST, SGST, IGST, cess, TDS, TCS, VAT…), their rates,
  and the rules that decide which apply are data an organization can view and edit — dated, so a
  rate change never rewrites history.
- **One engine** computes tax for every document type, so a quotation, the invoice made from it and
  a credit note against that invoice can never disagree.
- **Issued documents are frozen.** They store a snapshot of every tax line (component, rate, base,
  amount, and which rule/rate produced it). Changing configuration later never changes them.
- **Real-company flow.** Gapless numbering per registration and financial year, credit/debit notes as
  the only way to correct an issued invoice, TDS deducted by customers counted as settlement and
  reconciled later, e-invoicing, GST return data, ledger export.
- **India first, world-ready.** The India GST + TDS pack ships first; VAT, US sales tax, Canadian
  compound taxes etc. are additional packs on the same model.

Non-goals for the first phases: filing returns directly with the government, payroll TDS, purchase
side (input tax credit on vendor bills). The model should not block them later.

---

## 2. Research: how a real company's quote-to-cash works

```
Lead ─► Opportunity ─► Quotation (estimate; taxes shown, not owed)
                           │ accepted
                           ▼
                        Contract ─► Billing schedule (milestones / recurring / usage)
                                         │
                       ┌─────────────────┤
                       ▼                 ▼
        Proforma invoice (optional)   Advance received? → Receipt voucher (GST on advance for services)
        • own number series                  │
        • no tax liability                    │
                       │                      │
                       ▼                      ▼
                 Tax invoice  draft ─► issued ─► (e-invoice IRN if mandated)
                 • gapless no. per GSTIN + FY, ≤16 chars
                 • immutable once issued
                       │
      ┌────────────────┼──────────────────────────────┬──────────────────────┐
      ▼                ▼                              ▼                      ▼
 Credit note      Debit note                    Payment receipt          Collections
 (reduce value,   (increase value,              • bank amount            • dunning on the
  cancel, return;  extra charges)               • + TDS withheld by        net amount still
  ref. original;                                  customer (settles)       expected
  deadline:                                     • + GST-TDS (govt)       • promise-to-pay,
  30 Nov next FY)                               • bank charges             write-off
                                                • short-pay / write-off
                                                • advance / unallocated
                                                       │
                                                       ▼
                                          TDS receivable ─► match with Form 26AS / 16A
                                                       │
                                                       ▼
                         Books & returns: tax ledgers → Tally/Zoho export, GSTR-1 data, reports
```

What each step means for the system:

| Step | What a real finance team needs |
|---|---|
| Quotation | Line taxes visible to the customer; TDS shown as "you may deduct X"; totals frozen when sent. |
| Contract | Agreed prices and the **billing schedule** (advance %, milestones, monthly retainers). |
| Billing schedule | Each schedule line becomes a draft invoice on its date/milestone; nothing is billed twice. |
| Proforma | A request for payment before the tax invoice (common for advances). Own series, no GST liability; converts into a tax invoice. |
| Advance receipt | For **services**, GST is due when an advance is received → a *receipt voucher*; later adjusted against the invoice. (Goods: no GST on advances.) |
| Tax invoice | Supplier GSTIN, recipient GSTIN, place of supply, HSN/SAC, per-component tax, consecutive number unique per FY. Immutable after issue. |
| E-invoice | Above the turnover threshold, the invoice is registered with the IRP → IRN + signed QR printed on the invoice. Cancellation only within 24 h, otherwise by credit note. |
| Credit / debit note | Only way to change an issued invoice. References the original, reuses its tax treatment, has its own gapless series, time-limited. |
| Payment | Bank receipt + what the customer withheld (TDS, GST-TDS) + bank charges + write-offs, allocated per invoice. |
| TDS reconciliation | Each withheld amount is a receivable from the government until it shows in Form 26AS / a Form 16A certificate. |
| Collections | Chase the amount that is genuinely still owed (gross balance − expected withholding). |
| Books & returns | Every tax component posts to its own ledger; GSTR-1 needs B2B/B2C/exports/notes/HSN summaries. |

---

## 3. Research: tax rules that shape the design

### 3.1 GST (India)

- **Components.** Intra-state supply: **CGST + SGST** (or **UTGST** in union territories without a
  legislature) — half the rate each. Inter-state, export, SEZ: **IGST** at the full rate. **Cess** on
  some goods (mostly removed — see below).
- **Rates change, by date.** GST 2.0 took effect **22 Sep 2025**: the 12% and 28% slabs were removed;
  the structure is now mainly **0% / 5% / 18% / 40%**, and compensation cess was scrapped except for
  specific tobacco products until the cess loan is repaid. → Rates must be **effective-dated**; the
  rate applied depends on the *time of supply*, not on when someone opens the screen.
- **Place of supply (services, IGST Act s.12/13).** Generally the recipient's location for a
  registered recipient; the supplier compares it with its own registration's state to decide
  intra- vs inter-state. Special rules exist (immovable property, events, etc.) — keep a
  `place_of_supply` override on the document.
- **Supply types the engine must recognise:**
  - B2B intra-state, B2B inter-state
  - B2C (unregistered recipient) — large/small split matters for GSTR-1
  - **Export of services** — zero-rated: either under **LUT** (IGST 0%, no tax paid) or with IGST paid
    (refund claimed later)
  - **SEZ unit / developer** — zero-rated, same LUT / with-payment choice
  - **Reverse charge (RCM)** — some services: the *recipient* pays the GST; invoice shows tax as
    "payable on reverse charge"
  - Exempt, nil-rated, non-GST supplies — no tax but reported separately
  - Composition-scheme supplier — can't charge GST (issues a *bill of supply*) — needed only if an
    org itself is under composition
- **Invoice rules (Rule 46).** Consecutive serial number, **≤ 16 characters**, letters/digits/`-`/`/`,
  one or more series, **unique per financial year**. Mandatory fields: supplier name/address/GSTIN,
  number, date, recipient name/address/GSTIN (B2B), place of supply (state name + code), HSN/SAC,
  description, quantity/unit, taxable value, rate and amount per component, total, reverse-charge
  flag, signature.
- **Credit notes (s.34).** For excess value/tax, returns, deficient services. Deadline: **30 November
  after the end of the FY** of the original supply (or the annual return date, if earlier).
  Debit notes for undercharging.
- **E-invoicing.** Mandatory when aggregate annual turnover (AATO) in any FY since 2017-18 exceeds
  **₹5 crore**. With AATO ≥ **₹10 crore**, documents must be reported to the IRP within **30 days** of
  the document date or the IRP rejects them. IRN cancellation only within 24 hours.
- **GST-TDS (s.51)** — government bodies deduct 2% (1% CGST + 1% SGST, or 2% IGST) on payments above
  a threshold. **GST-TCS (s.52)** — e-commerce operators collect on sales through them. Both reduce
  the cash received and are credited to the supplier's electronic cash ledger.
- **Rounding.** Tax per line is computed to paise; invoices commonly round the grand total to the
  nearest rupee with a visible "Round off" line.

### 3.2 TDS (income tax withholding)

- The **customer** (deductor) withholds TDS from what it pays you and deposits it with the government.
  It **does not change the invoice total**; it counts toward settling the invoice, and you hold a
  **TDS receivable** until it appears in **Form 26AS** / you get a **Form 16A** certificate, then claim
  it against your own income tax.
- **Base excludes GST** when GST is shown separately on the invoice (CBDT Circular 23/2017).
- **Renumbered from 1 April 2026.** The Income-tax Act 2025 replaced the 1961 Act; the old sections
  (194C contractors, 194J professional/technical, 194H commission, 194I rent, 194Q purchase of goods…)
  were consolidated into **Section 393** with **payment codes** (e.g. 1023, 1026, 1027, 1031). Documents
  dated before the change keep the old references. → Withholding sections must be **dated data with
  aliases** (old section ↔ new section/payment code).
- Typical rates (verify before seeding): professional services 10%, technical services 2%,
  contractors 1% (individual/HUF) / 2% (others), commission 2%; thresholds per year/per payment;
  **lower/nil deduction certificates** give a customer a reduced rate for a period and amount.
- **TCS (collected at source)** — the reverse of TDS: the *seller* collects extra tax on certain sales.
  Rare for services; supported by the same model ("collected" kind).

### 3.3 Consequences for the design

| Fact | Design consequence |
|---|---|
| Rates change by notification (GST 2.0) | `tax_rates.effective_from/effective_to`; engine looks up by document/supply date |
| Sections renumbered (393) | `withholding_sections` with aliases and effective dates |
| Intra vs inter vs export vs SEZ vs RCM | Rules keyed on a computed **supply type**, not hardcoded `if` |
| TDS on pre-GST value, doesn't change total | Withholding is a separate **kind** with its own base; shown as "net receivable" |
| Invoices immutable; credit notes reuse original tax | Store **tax line snapshots**; notes copy the original's lines proportionally |
| Gapless per GSTIN per FY, ≤16 chars | `invoice_series` row per (registration, doc type, FY) with locked increment + format validation |
| E-invoice thresholds/time limits | Registration-level flags + background job + deadline warnings |

---

## 4. Research: how tax engines are modelled elsewhere

- **Odoo**: taxes are records with type (percent / fixed / group / division), *included in price*
  flag, sequence for **compound** taxes ("affect base of subsequent taxes"), tax **groups**, and
  **fiscal positions** that map taxes per customer region/type (e.g. "Inter-state", "Export").
  Country localisations ship as templates.
- **Stripe Tax**: tax **codes** on products (what is sold), **tax behavior** inclusive/exclusive on
  prices, jurisdiction-aware tax rates, and a standalone *calculate* API returning line-level
  breakdowns.
- **Avalara / Vertex**: a calculation service fed with ship-from/ship-to addresses, product tax codes
  and customer exemption certificates; returns jurisdiction-level tax lines. Used where rate data is
  too large to maintain (US sales tax).

Common pattern we adopt: **components + dated rates + rules (conditions → components) + product tax
categories + party profiles**, a **pure calculate function** returning a line-level breakdown, and
**templates per country**. The engine interface should allow an external provider to replace the
internal rule evaluation for a regime (US sales tax).

---

## 5. What exists in FBOS today (and what's wrong)

All in `src/v1/02_revenue` unless noted.

### 5.1 Inventory

| Area | Where | Today |
|---|---|---|
| Quotation totals | `services/quotation_service.py:36` `calculate_tax_and_totals` | per line: qty × price − discount%, GST from offering, CGST/SGST vs IGST by state compare |
| Quotation storage | `models/quotation.py` | `subtotal`, `discount_total`, `tax_total`, `grand_total`; items store `gst_rate`, `net_price`, `line_total` |
| Invoice totals | `services/invoice_service.py:39` `calculate_invoice_lines` | same logic, separate copy |
| Invoice storage | `models/invoice.py` | `taxable_total`, `cgst_total`, `sgst_total`, `igst_total`, `grand_total`, `amount_settled`, `balance_due`, `supplier_gstin`, `recipient_gstin`, `place_of_supply`, `client_snapshot`; lines store `hsn_code`, `taxable_value`, `cgst/sgst/igst_amount` |
| Numbering | `invoice_service.py:353-361`, `:434` | `count()+1`, FY string hardcoded |
| Series table | `models/invoice_series.py` | `InvoiceSeries(fin_registration_id, doc_type, prefix, fiscal_year, next_number)` — **unused** |
| Billing schedule | `models/billing.py` | `BillingSchedule`, `BillingScheduleLine(invoice_id, milestone, due_date, amount)` — **unused** |
| Contract payment terms | `models/contract.py` `ContractPaymentTerm` | advance / milestone / on_completion %, due offset |
| Payments | `services/payment_service.py` | one `tds_amount` per payment added to `unapplied_amount`; allocations per invoice |
| Accounting export | `models/accounting.py` `AccountingExport` | tracking table only |
| Offering tax | `models/offering.py` | `sac_code`, `gst_code` (string parsed as a rate) |
| Client tax | `models/client.py` | `gstin`, `billing_address.state_code` |
| Supplier registrations | `01_identity/models/legal.py` | `LegalEntity(legal_name, pan)`, `TaxRegistration(legal_entity_id, branch_unit_id, pin, regime_code, registered_address, valid_from)` — no API routes |
| Organization | `01_identity/models/organization.py` | `base_currency`, `fiscal_year_start` (DD-MM), `timezone` |

### 5.2 Defects found

| # | Defect | Where |
|---|---|---|
| D1 | Supplier GSTIN hardcoded `"29AABCF9876L1Z3"`; supplier state `"29"` (Karnataka) default everywhere | `invoice_service.py:42,237-244`, `quotation_service.py:40,162,216-220,337` |
| D2 | Invoice line response always returns `gst_rate=18.0` — the rate isn't stored on invoice lines | `invoice_service.py:121`, `models/invoice.py` |
| D3 | Full credit note recomputes with `gst_rate=18.0` regardless of the original's rate | `invoice_service.py:422` |
| D4 | Credit note sets the original invoice to **"paid"** / "partially_paid" | `invoice_service.py:490` |
| D5 | Numbering by `count()+1` — not concurrency-safe, not per GSTIN, FY hardcoded `"26-27"`, prefix hardcoded | `invoice_service.py:353-361,434`, `payment_service.py:186` |
| D6 | Reading a quotation back splits `tax_total` into CGST/SGST halves and IGST=0 — inter-state quotations display wrongly after save | `quotation_service.py:301-303,495-497` |
| D7 | Currency forced to `"INR"` in totals | both calculators |
| D8 | Money as `float`; no rounding policy; no round-off line | throughout |
| D9 | TDS is one number per payment — no per-invoice amount, section, rate, or receivable tracking | `payment_service.py` |
| D10 | No credit-note deadline check, no debit notes, no proforma flow, no RCM / export / SEZ / LUT handling | — |
| D11 | Two duplicated tax calculators (quotation vs invoice) | — |
| D12 | API spec puts billing at `/api/billing/v1` with `billing.*` permissions; code serves it in revenue under `revenue.invoice.*` | spec vs `routes/invoices.py` |

---

## 6. Design principles

1. **Configuration over code.** No tax names, rates or state codes in Python except in seed templates.
2. **Dated everything.** Rates, rules, sections and registrations carry `effective_from` / `effective_to`.
   The engine evaluates "as of" the document's tax point date.
3. **Pure engine.** `calculate(context) -> TaxResult` does no I/O; callers load config and party
   profiles and pass them in. Easy to unit-test exhaustively and to reuse for previews.
4. **Snapshot on issue.** Documents persist tax lines with the component code, label, rate, base,
   amount and the ids of the rule/rate used. Issued documents are never recalculated.
5. **Decimal money** with explicit, per-regime rounding; amounts stored as `Numeric(18, 2)` (and
   rates as `Numeric(9, 4)`).
6. **Backwards-compatible API.** Existing `cgst/sgst/igst` fields keep returning (computed from tax
   lines) until the frontend moves to the generic `taxes[]` list.
7. Follow `.agents/` rules: early returns, external systems behind adapters (IRP, accounting export,
   external tax providers), useful error codes, focused changes.

---

## 7. Data model — tax configuration

All tables are per `organization_id` (copied from a template on org bootstrap), in the revenue
(billing) service. Names are proposals.

### 7.1 `tax_regimes`
A tax system.

| Column | Type | Notes |
|---|---|---|
| id | uuid | |
| organization_id | uuid | |
| code | str | `IN-GST`, `IN-ITD` (income-tax withholding), `AE-VAT`, `EU-VAT`, `US-SALES`, `CA-GST` |
| name | str | |
| country | str(2) | ISO country |
| kind | enum | `indirect` (charged on supply), `withholding` (deducted by payer), `collected` (TCS) |
| rounding_mode | enum | `half_up` (default), `half_even`, `up`, `down` |
| rounding_level | enum | `line` / `document` |
| document_round_off | enum | `none`, `nearest_1` (₹1), `nearest_0_05`… |
| provider | enum | `internal` (rules below) or `external:<name>` (Avalara/Stripe adapter) |
| status | enum | active / archived |

### 7.2 `tax_components`
One tax that can appear as its own line.

| Column | Type | Notes |
|---|---|---|
| id, organization_id, regime_id | | |
| code | str | `CGST`, `SGST`, `UTGST`, `IGST`, `CESS`, `VAT`, `QST`, `TDS`, `GST_TDS_CGST`… |
| name / print_label | str | label on documents ("Central GST") |
| behaviour | enum | `added` (increases total), `withheld` (payer deducts; reduces net receivable), `collected` (TCS, increases total but separate), `reverse_charge` (shown, not charged) |
| base | enum | `taxable_value` (default) or `taxable_plus_previous` (compound — base includes earlier components with lower `sequence`) |
| sequence | int | evaluation order for compound taxes |
| calc_type | enum | `percent`, `fixed_per_unit`, `percent_plus_fixed` |
| ledger_account_code | str | e.g. `Output CGST`, `TDS Receivable` — drives accounting export |
| return_box | str | reporting bucket (e.g. GSTR-1 column) |
| status | | |

### 7.3 `tax_rates`
Value of a component over time (a component may have several rates — 5%, 18%, 40% IGST).

| Column | Type | Notes |
|---|---|---|
| id, component_id | | |
| code | str | `IGST_18` |
| rate_percent | Numeric(9,4) | nullable for fixed |
| fixed_amount / fixed_unit | Numeric / str | per-unit cess |
| effective_from | date | inclusive |
| effective_to | date? | exclusive; null = open |
| notification_ref | str | e.g. the notification that introduced it — for audit |

Constraint: no overlapping effective ranges for the same `code`.

### 7.4 `tax_categories`
What is being sold. Offerings and document lines point to a category.

| Column | Notes |
|---|---|
| code / name | `SVC_18` "Services – 18%", `GOODS_5`, `EXEMPT`, `NIL`, `NON_GST`, `ZERO_RATED` |
| classification_code | HSN/SAC default (overridable per offering/line) |
| treatment | `taxable`, `exempt`, `nil_rated`, `non_gst` — exempt/nil/non-GST produce no tax but are reported |
| effective_from / effective_to | categories can be retired when slabs change |

### 7.5 `tax_rules`
Decides which components (at which rates) apply.

| Column | Notes |
|---|---|
| regime_id, priority | higher priority wins when several match |
| conditions (JSON, validated) | any of: `supply_type` in […], `category` in […], `customer_registration_type` in […], `supplier_state` / `place_of_supply` in […], `customer_country` in […], `reverse_charge` bool, `document_type` in […], `amount_threshold` |
| outputs | ordered list of `{component_code, rate_code}` (e.g. `[CGST_9, SGST_9]`) or `{component_code, rate_from_category: true}` |
| notes_on_document | text printed on the invoice (e.g. "Supply meant for export under LUT without payment of IGST", "Tax payable on reverse charge") |
| effective_from / effective_to | |

Conditions are a small, explicit set (validated with Pydantic), not a free-form expression language —
easy to reason about and to show in the admin UI as "When … then …".

**India pack rules (illustrative):**

| Priority | When | Then |
|---|---|---|
| 100 | category treatment ∈ {exempt, nil_rated, non_gst} | no tax; note "Exempt supply" |
| 90 | reverse_charge = true | components shown with behaviour `reverse_charge`; note "Tax payable on reverse charge" |
| 80 | supply_type = export, lut = valid | IGST 0%; note "Export under LUT without payment of IGST" |
| 80 | supply_type = sez, lut = valid | IGST 0%; SEZ note |
| 70 | supply_type ∈ {export, sez} | IGST at category rate (with payment) |
| 50 | supply_type = intra_state, place in UT without legislature | CGST + UTGST at half rate |
| 40 | supply_type = intra_state | CGST + SGST at half rate |
| 40 | supply_type = inter_state | IGST at category rate |

### 7.6 `withholding_sections`
Income-tax withholding (TDS) / TCS law.

| Column | Notes |
|---|---|
| code | `IN-393-PROF` |
| statute_ref | `Sec 393(1) Sl.6(iii)`; `payment_code` `1026` |
| aliases | `["194J"]` (old Act) — for documents before 2026-04-01 and for users who search by old numbers |
| nature | "Fees for professional services" |
| rate_percent (by deductee type) | JSON `{company: 10, individual: 10, no_pan: 20}` |
| threshold_single / threshold_annual | |
| base | `pre_tax_value` (default) / `gross` |
| effective_from / effective_to | |

### 7.7 Templates
`tax_templates/in_gst_tds.yaml` (code-reviewed seed): regimes, components, rates with notification
references, categories, rules, withholding sections. Copied into an organization on bootstrap (or on
first use, like document categories). A "template version" lets us ship updates (e.g. a new slab) that
admins review and apply.

---

## 8. Data model — party tax profiles

### 8.1 Supplier: the organization's registrations (identity)
Extend identity `tax_registrations` (the spec already references `tax_registration_id`):

| Field | Notes |
|---|---|
| regime_code | `IN-GST` |
| pin | GSTIN (validate format + checksum; first 2 digits = state code) |
| state_code | derived from GSTIN (stored for querying) |
| registration_type | regular / composition / SEZ unit / ISD… |
| legal_entity_id, branch_unit_id | existing |
| e_invoice_applicable | bool (from AATO) |
| e_invoice_30_day_limit | bool (AATO ≥ ₹10 Cr) |
| lut_number, lut_valid_from, lut_valid_to | for zero-rated supplies without payment |
| default_series_prefixes | per doc type, e.g. `{tax_invoice: "INV/", credit_note: "CN/"}` |
| valid_from / valid_to | existing + new |

Identity needs **routes** for legal entities and registrations (none exist today) and an internal read
endpoint revenue can call (or revenue caches a copy — see open decisions).

### 8.2 Customer: tax profile (revenue `clients` → new `client_tax_profiles`, or columns)

| Field | Notes |
|---|---|
| registration_type | `registered`, `unregistered`, `composition`, `sez_unit`, `sez_developer`, `overseas`, `government`, `un_body` |
| gstin | existing column; validated |
| default_place_of_supply | state code; from billing address otherwise |
| country | for exports |
| tds_deductor | bool |
| tds_section_id | default withholding section (e.g. professional services) |
| deductee_type | company / individual / … (selects TDS rate) |
| lower_deduction_certificates | list: certificate no., rate, valid_from/to, amount limit |
| gst_tds_deductor | bool (government bodies) |
| tax_exemptions | e.g. US exemption certificates, EU VAT number for reverse charge |

### 8.3 Offering
Replace `gst_code` with `tax_category_id` (+ optional `classification_code` override = SAC/HSN) and
`price_includes_tax` (inclusive/exclusive). Keep `sac_code` as the default classification.

---

## 9. The tax engine

Package: `src/v1/02_revenue/tax/` — `engine.py` (pure), `context.py` (input dataclasses),
`result.py`, `rules.py` (condition matching), `rounding.py`, `supply_type.py`, `providers/` (internal,
external adapters), `loader.py` (reads config from DB → engine input).

### 9.1 Input (`TaxContext`)

```text
TaxContext
  regime_codes: ["IN-GST", "IN-ITD"]
  tax_point_date: date               # supply/invoice date — selects rates & rules
  document_type: quotation | proforma | tax_invoice | credit_note | debit_note
  currency, exchange_rate_to_base
  supplier: { registration_id, gstin, state_code, registration_type, lut_valid: bool }
  customer: { registration_type, gstin, country, place_of_supply, tds: {...}|None, gst_tds_deductor }
  place_of_supply_override: str | None
  reverse_charge: bool
  lines: [ { line_no, category_code, classification_code, quantity, unit_price,
             discount_percent | discount_amount, price_includes_tax } ]
  config: snapshot of components, rates, categories, rules, sections valid on tax_point_date
```

### 9.2 Algorithm

1. **Supply type** (`supply_type.py`):
   - customer overseas → `export`
   - customer SEZ → `sez`
   - place of supply (override → customer default → billing address state) vs supplier state:
     equal → `intra_state`, else `inter_state`
   - unregistered customer → B2C flag (for reporting)
2. **Per line**:
   1. Taxable value: `qty × unit_price − discount`. If `price_includes_tax`, back-calculate:
      `taxable = gross / (1 + Σ added rates)` (for compound: solve in sequence order).
   2. Category treatment exempt/nil/non-GST → no tax lines; mark for reporting.
   3. Pick the highest-priority **rule** whose conditions match and whose dates cover
      `tax_point_date`. No match → error `TAX_RULE_NOT_FOUND` (never silently 0%).
   4. For each output `{component, rate}` in `sequence` order: base = taxable value (or taxable +
      earlier components if compound); amount = base × rate (or fixed × qty); round per regime.
   5. Behaviour `reverse_charge` → record the line but exclude it from the total.
3. **Document level**: sum per component; if `rounding_level = document`, compute on summed bases
   instead; apply `document_round_off` → `round_off` amount.
4. **Withholding preview** (if the customer is a TDS deductor): base = Σ taxable values (pre-GST),
   rate from section × deductee type, or lower-deduction certificate if valid on the date and within
   its limit → `withholding[]` and `net_receivable = grand_total − Σ withheld`.
5. **Explain**: for every tax line, the rule id, rate id and the conditions that matched.

### 9.3 Output (`TaxResult`)

```text
TaxResult
  supply_type, place_of_supply, reverse_charge
  lines: [ { line_no, taxable_value, taxes: [ {component_code, label, rate, base, amount,
                                               behaviour, rule_id, rate_id} ], line_total } ]
  totals: { subtotal, discount_total, taxable_total,
            taxes: [ {component_code, label, rate?, amount} ],   # e.g. CGST 9%, SGST 9%
            round_off, grand_total }
  withholding: [ {section_code, statute_ref, rate, base, amount} ]
  net_receivable
  notes: [ "Supply meant for export under LUT …" ]
  report_buckets: { gstr1_section: "B2B" | "B2CL" | "B2CS" | "EXP" | …, hsn_summary: [...] }
```

### 9.4 Errors (useful, specific)

| Code | When |
|---|---|
| `TAX_RULE_NOT_FOUND` | no rule matches a line (config gap) — names the line and conditions |
| `TAX_RATE_NOT_EFFECTIVE` | rule points to a rate not valid on the tax point date |
| `SUPPLIER_REGISTRATION_REQUIRED` | no active registration for the organization/regime |
| `PLACE_OF_SUPPLY_UNKNOWN` | can't determine place of supply and none given |
| `GSTIN_INVALID` | format/checksum failure |
| `LUT_EXPIRED` | zero-rated without payment requested but LUT not valid on the date |

---

## 10. Documents

### 10.1 Shared line-tax storage
New table `document_line_taxes` (one per line per component), used by quotation items, invoice lines
(all doc types):

| Column | Notes |
|---|---|
| id, document_type, document_id, line_id | polymorphic or separate FK per table |
| component_code, label, behaviour | snapshot (not FK — config may change later) |
| rate_percent, fixed_amount | snapshot |
| base_amount, tax_amount | Numeric(18,2) |
| rule_id, rate_id | for audit/explain |

Plus per document: `supply_type`, `place_of_supply`, `reverse_charge`, `round_off`,
`tax_point_date`, `currency`, `exchange_rate`, `notes`, and a `withholding_preview` JSON.
Line tables gain `tax_category_code`, `classification_code` (HSN/SAC), `price_includes_tax`.

The old `cgst/sgst/igst` columns stay readable during migration (section 17), then are dropped.

### 10.2 Quotation
- Draft: recompute through the engine on every line change (`POST /tax/calculations` for previews).
- **Sent**: freeze (snapshot) — later config changes don't alter what the customer received.
- Revisions copy lines and recompute (the new revision is a new offer).
- Show withholding as information ("Customer may deduct TDS ₹X; net receivable ₹Y").

### 10.3 Contract → billing schedule
- On activation, generate `billing_schedules` + `billing_schedule_lines` from `ContractPaymentTerm`
  (advance %, milestones, on completion, recurring with frequency/end date).
- Each schedule line: `planned_date` or `milestone_code`, amount/percent, status
  `planned → ready → invoiced → cancelled`, `invoice_id`.
- A job (or a user action "Bill now") creates a **draft invoice** from a ready line, with the
  contract's terms; never bills a line twice (unique `schedule_line_id` on invoices).
- Milestone readiness can later come from delivery events (`work.milestone.completed`).

### 10.4 Proforma
- `doc_type = proforma`, own series, no tax liability, no e-invoice.
- Shows taxes (engine) so the customer knows the final amount.
- "Convert to tax invoice" creates the tax invoice with the same lines (recomputed at the actual tax
  point date) and links them.

### 10.5 Advance receipts (services)
- A payment received before an invoice for a service → **receipt voucher** with GST on the advance
  (engine computes on the advance, treated as tax-inclusive per common practice — confirm with the CA).
- When the invoice is issued, the advance and its tax are adjusted; refund voucher if the service
  is cancelled. Phase 3+.

### 10.6 Tax invoice lifecycle
`draft → (pending_approval) → issued → partially_paid → paid` with side states `overdue`,
`cancelled` (fully credited or IRN-cancelled within 24h), `written_off`.

**Issue** (one transaction):
1. Validate: supplier registration active on the issue date; issue date not in a closed period and
   not in the future; lines have categories; engine result recomputed and frozen.
2. **Number**: `SELECT … FOR UPDATE` the `invoice_series` row for (registration, doc_type, FY);
   format `prefix + FY + "/" + zero-padded next_number`; validate ≤16 chars and allowed characters;
   increment. FY from the organization's `fiscal_year_start` (e.g. 01-04 → "26-27").
3. Snapshot client (legal name, GSTIN, address, state) and supplier (GSTIN, address).
4. Status `issued`; publish `billing.invoice.issued.v1`.
5. After commit: PDF render (documents service), e-invoice job if applicable, email.

**Approval threshold** (spec): above an org-configured amount → `APPROVAL_REQUIRED` with an approval
request (control service).

### 10.7 E-invoice (IRP)
- Adapter interface `EInvoiceProvider` (`generate_irn(invoice) → {irn, ack_no, ack_date, signed_qr,
  signed_invoice}`, `cancel_irn(irn, reason)`), implemented per GSP (ClearTax, Masters India, IRIS…)
  plus a **sandbox stub**.
- Background job with retries; invoice `e_invoice_status`: `not_applicable | pending | generated |
  failed | cancelled`.
- 30-day rule: warn at day 20/25 for registrations flagged `e_invoice_30_day_limit`; block after 30.
- Cancellation only within 24 hours of IRN; afterwards only a credit note.

### 10.8 Credit and debit notes
- Endpoint per spec: `POST /invoices/{id}/credit-notes` (and `/debit-notes`).
- Reason: `price_correction`, `service_deficiency`, `cancellation`, `return`, `other`.
- **Tax treatment copied from the original** (same supply type, place of supply, rates): full
  credit = negate every original tax line; partial = proportional by line or explicit amounts —
  never re-derived from today's config. (Fixes D3.)
- **Deadline**: block (or require override with reason) after 30 Nov following the FY of the original.
- Own gapless series per registration/FY.
- Effect on the original: `credited_amount += note total`, `balance_due` recomputed; if fully
  credited and unpaid → `cancelled`; never `paid`. (Fixes D4.)
- If the original was already paid → the credit becomes **customer credit** (refund or apply to
  another invoice).
- Debit notes increase the receivable; they are payable like invoices.

---

## 11. Payments, TDS and receivables

### 11.1 Receipt
`payments`: client, received_on, amount (bank), currency + exchange rate, method, bank reference,
**bank_charges**, status (`pending | confirmed | failed | refunded | partially_refunded`), gateway ids.

### 11.2 Allocation per invoice (replaces the single `tds_amount`)
`payment_allocations` gain settlement components:

| Field | Meaning |
|---|---|
| cash_amount | money from this receipt applied to the invoice |
| tds_amount, tds_section_id, tds_rate | income-tax withheld by the customer **for this invoice** |
| gst_tds_amount | GST-TDS (s.51) withheld by government customers |
| tcs_amount | if applicable |
| write_off_amount, write_off_reason | small short-payments, discounts allowed |
| allocated_at | |

`invoice.amount_settled += cash + tds + gst_tds + tcs + write_off`; `balance_due` recomputed.
Validation: sum of cash allocations ≤ receipt amount − bank charges; TDS ≤ expected TDS (warn if the
rate differs from the customer's section/certificate).

### 11.3 TDS receivable & reconciliation
`tds_receivables` (one row per allocation with TDS):

| Field | Notes |
|---|---|
| client (deductor), deductor TAN | |
| section / payment code, rate, base, amount | |
| quarter / FY | |
| status | `expected → reflected_in_26as → certificate_received → claimed` / `mismatch` / `written_off` |
| certificate no. (16A), matched 26AS entry ref | |

- **Import** Form 26AS / TRACES data (CSV/text) and auto-match by deductor TAN + amount + period;
  manual match UI for the rest.
- Reports: unreconciled TDS by customer/quarter, aging, mismatch list (customer deducted at a
  different rate or on the GST component).

### 11.4 Advances, overpayments, refunds
- Unallocated money stays on the receipt as **customer advance**; it can be allocated later (and, for
  services, triggers a receipt voucher — 10.5).
- Refunds create negative receipts linked to the original; credit-note credit can be refunded.

### 11.5 Collections
- Work on **net expected** = `balance_due − expected withholding not yet booked`, so collectors don't
  chase TDS the customer correctly kept.
- Existing collection cases/dunning stay; amounts switch to net expected.

---

## 12. Accounting, returns and reports

### 12.1 Ledger mapping & export
- Every component/section carries `ledger_account_code`; receivables, bank, round-off, write-off,
  bank charges, advances each map to an account in org settings.
- On issue/payment, build a **journal** (debits/credits) from the snapshot; `AccountingExport` queues
  it for Tally (XML) / Zoho Books / QuickBooks adapters.

### 12.2 GST return data (GSTR-1)
- Each issued document records its **GSTR-1 bucket**: B2B, B2CL (inter-state B2C above the limit),
  B2CS, EXP (with/without payment), CDNR/CDNUR (notes), plus **HSN/SAC summary** and document
  summary (series used, cancelled numbers).
- Export as the GSTN offline-tool JSON/CSV per period; later, filing via the GSP.

### 12.3 Reports
Tax register (by component/rate/period), sales register, HSN summary, credit-note register, TDS
receivable aging, e-invoice status, LUT usage (zero-rated supplies), revenue by place of supply.

---

## 13. Beyond India

Same tables, different templates:

| Regime | How it maps |
|---|---|
| **UAE / GCC VAT** | one component `VAT` 5%, categories standard/zero/exempt; reverse charge rule for imports of services |
| **EU VAT** | components per country rate; rule: B2B cross-border with valid VAT number → reverse charge (0% + note); B2C digital services → customer-country rate (OSS) |
| **UK VAT** | 20% / 5% / 0%; reverse charge for specified services |
| **Canada** | GST 5% + PST, or HST; **QST compound** in older rules → `base = taxable_plus_previous` |
| **Australia / NZ** | GST 10% / 15%, prices commonly **inclusive** |
| **US sales tax** | state + county + city + district stacking by destination; thousands of rates → `provider = external:avalara` (or Stripe Tax) behind the same engine interface; exemption certificates on the customer profile |
| Other withholding taxes | `withholding_sections` per country (e.g. foreign withholding on services) |

Multi-currency: documents carry `currency` + `exchange_rate` (to the org's `base_currency`) snapshot at
the tax point; tax ledgers and reports in base currency; realised FX gain/loss on payment in a later
phase.

---

## 14. API surface

Base path: `/api/revenue/v1` today (or `/api/billing/v1` per the spec — see open decisions).

### 14.1 Configuration
| Method | Path | Notes |
|---|---|---|
| GET/POST | `/tax/regimes` | |
| GET/PATCH | `/tax/regimes/{id}` | rounding, provider, status |
| GET/POST | `/tax/components` | |
| GET/POST | `/tax/rates` | effective-dated; no overlaps |
| PATCH | `/tax/rates/{id}` | only `effective_to` once used on an issued document |
| GET/POST/PATCH | `/tax/categories` | |
| GET/POST/PATCH | `/tax/rules` | |
| GET/POST/PATCH | `/tax/withholding-sections` | |
| GET | `/tax/templates` | available packs and versions |
| POST | `/tax/templates/{code}/applications` | apply/upgrade a pack (preview diff first) |
| POST | `/tax/calculations` | preview: TaxContext-like body → TaxResult (no persistence) |

### 14.2 Profiles
| Method | Path |
|---|---|
| GET/PUT | `/clients/{id}/tax-profile` |
| GET/POST | `/clients/{id}/tax-profile/lower-deduction-certificates` |
| GET/POST/PATCH | identity: `/legal-entities`, `/legal-entities/{id}/tax-registrations` |

### 14.3 Documents & money
| Method | Path |
|---|---|
| … | quotations: unchanged routes; response gains `taxes[]`, `withholding[]`, `net_receivable`, `supply_type` |
| POST | `/proformas`, `POST /proformas/{id}/tax-invoices` (convert) |
| POST | `/invoices`, `/invoices/{id}/issue`, `/invoices/{id}/credit-notes`, `/invoices/{id}/debit-notes` |
| POST | `/invoices/{id}/e-invoice` (retry), `DELETE /invoices/{id}/e-invoice` (cancel IRN within 24h) |
| GET/POST | `/billing-schedules`, `POST /billing-schedules/{id}/lines/{line_id}/invoices` ("bill now") |
| POST | `/payments` (allocations carry tds/gst_tds/write-off) |
| GET | `/tds-receivables`, `POST /tds-receivables/imports` (26AS), `PATCH /tds-receivables/{id}` (match) |
| GET | `/reports/gstr1?period=2026-09`, `/reports/hsn-summary`, `/reports/tax-register` |

All writes: `Idempotency-Key`; updates: `If-Match`; errors in the existing `{detail: {code, message}}`
shape.

---

## 15. Permissions

Add to identity's `permission_catalog.py`:

| Code | Meaning |
|---|---|
| `revenue.tax.read` | view tax configuration and tax reports |
| `revenue.tax.manage` | edit regimes/components/rates/rules/categories, apply templates |
| `revenue.tax_profile.write` | edit customer tax profiles / certificates |
| `revenue.invoice.issue` | issue invoices (separate from drafting, per spec) |
| `revenue.credit_note.issue` | issue credit/debit notes |
| `revenue.tds.reconcile` | import 26AS, match TDS |
| `revenue.report.tax` | GSTR-1 / tax registers export |

(Or `billing.*` equivalents if billing moves to its own prefix.)

---

## 16. Frontend (clientadmin)

New feature `src/features/tax/`:
- **Tax settings**: regimes, components, rates (timeline view per component), categories, rules
  ("When … then …" editor), withholding sections, template apply/upgrade with diff preview.
- **Customer tax profile** tab on the customer page (registration type, GSTIN validation, TDS
  section, certificates).
- **Offering form**: tax category picker instead of a GST % field.
- **Quotation & invoice editors**: live preview via `/tax/calculations`; totals block renders the
  generic `taxes[]` list, round-off, withholding and net receivable; notes (LUT/RCM) shown.
- **Invoice detail**: e-invoice status/IRN/QR, credit/debit note actions with deadline hint.
- **Payment form**: per-invoice allocation rows with cash, TDS (section prefilled from the customer),
  GST-TDS, write-off; bank charges.
- **TDS reconciliation** screen: import 26AS, auto-match results, manual match.
- **Reports**: GSTR-1 export, tax register, TDS aging.

---

## 17. Migration from the current schema

1. **Config**: create tables; seed the India pack for every organization.
2. **Offerings**: map `gst_code` (rate) → category (`18` → `SVC_18`, `5` → `SVC_5`, `0` → `EXEMPT`
   or `ZERO_RATED` — ask the org if ambiguous); keep `sac_code` as classification.
3. **Quotation items / invoice lines** → `document_line_taxes`:
   - invoices: `cgst_amount`/`sgst_amount`/`igst_amount` → one row each when non-zero; rate =
     amount / taxable_value (rounded to the nearest known slab; flag mismatches);
   - quotations: only `tax_total` + `gst_rate` exist → derive split from `place_of_supply` vs the
     supplier state at the time (`"29"` default) and flag them as *migrated*.
4. **Supplier GSTIN**: create the organization's `tax_registration` from the hardcoded value only if
   the org confirms it; otherwise leave existing documents with their stored `supplier_gstin`.
5. **Series**: initialise `invoice_series.next_number` per (registration, doc type, FY) from the max
   existing number so numbering continues without gaps.
6. **Payments**: move each payment's `tds_amount` onto its allocations proportionally (or onto the
   first allocation) and create `tds_receivables` rows with status `expected`.
7. Keep the old columns read-only for one release; API computes `cgst/sgst/igst` from tax lines;
   then drop the columns in a later migration.

All as Alembic migrations in `02_revenue/migrations` (and identity for registrations), each reversible
where data allows.

---

## 18. Testing strategy

- **Engine unit tests (table-driven)** — the bulk of the testing:
  - intra-state 18% → CGST 9 + SGST 9; inter-state → IGST 18; UT → CGST + UTGST
  - export with valid LUT → IGST 0 + note; LUT expired → error or with-payment rule
  - SEZ; reverse charge (tax shown, not in total); exempt / nil / non-GST
  - inclusive pricing back-calculation; compound tax (QST-style); fixed per-unit cess
  - rate change boundary: tax point 2025-09-21 vs 2025-09-22
  - rounding: line vs document; round-off to ₹1; paise edge cases (0.005)
  - TDS base excludes GST; lower-deduction certificate valid / expired / limit exhausted
  - section alias before/after 2026-04-01
  - no rule → `TAX_RULE_NOT_FOUND`
- **Service tests** (existing pytest + SQLite setup): issue numbering under concurrency (two issues
  at once → consecutive numbers, no duplicates), FY rollover, 16-char validation, credit note copies
  original tax and respects the deadline, credit never marks "paid", payment with TDS settles invoice
  and creates a receivable, 26AS import matching.
- **Migration tests**: run migrations on a copy of seeded data; totals before == totals after.
- **E2E smoke**: quotation → contract → schedule → invoice → payment with TDS → reconciliation.

---

## 19. Phased delivery

| Phase | Contents | Done when |
|---|---|---|
| **1. Foundation** | config tables + India template + engine (pure) + exhaustive unit tests; supplier registration source (identity routes or revenue copy); offering → category | engine tests green; `/tax/calculations` preview works |
| **2. Documents** | `document_line_taxes`; quotations & invoices on the engine; fixes D1–D8, D11; numbering via `invoice_series`; credit/debit notes rebuilt; migration of existing data; API keeps `cgst/sgst/igst` | quotation/invoice/credit note tests + migration tests green |
| **3. Payments** | per-allocation TDS/GST-TDS/write-off, bank charges, TDS receivables + 26AS import/match, advances/refunds, collections on net expected | payment + reconciliation tests green |
| **4. Billing schedules & proformas** | generate schedules from contracts, bill-now, proforma + convert, advance receipt vouchers | contract → invoices flow works end to end |
| **5. Compliance** | e-invoice adapter + sandbox, 30-day warnings, GSTR-1 data/export, ledger mapping + Tally export | sandbox IRN generated; GSTR-1 JSON validates in the offline tool |
| **6. International** | one non-India pack (e.g. UAE VAT or EU VAT), multi-currency + exchange rates, external provider interface | pack works without code changes to the engine |
| **Frontend** | alongside each phase (section 16) | |

Rough order of effort: phase 1–2 are the largest and must land first; 3 is independent of 4; 5 needs
2; 6 needs 1–2.

---

## 20. Open decisions

1. **Where billing lives**: keep in revenue (`/api/revenue/v1`, `revenue.*`) or move to the spec's
   `/api/billing/v1` with `billing.*` permissions while it is rebuilt?
2. **Supplier registrations**: identity owns them (spec) — needs new identity routes + an internal read
   endpoint — or revenue keeps its own copy?
3. **E-invoice provider (GSP)**: which one (ClearTax, Masters India, IRIS, …)? Until chosen: adapter +
   sandbox stub.
4. **First non-India pack**: none yet, or one (UAE/EU VAT) to prove the model?
5. **Rounding policy** per org: line-level vs document-level; round-off to ₹1 on/off (confirm with
   the organization's CA).
6. **Advance receipts for services**: needed in phase 3, or later?
7. **Credit-note deadline**: hard block or allow with an override reason + permission?
8. **Template updates**: auto-apply new government rates, or always require admin review?

---

## 21. Worked examples

### 21.1 Intra-state service with discount (today's example)
Supplier GSTIN state 29, customer state 29, category `SVC_18`, 2 × ₹100,000, 30% discount.

| | |
|---|---|
| Subtotal | 200,000.00 |
| Discount (30%) | −60,000.00 |
| Taxable | 140,000.00 |
| CGST 9% | 12,600.00 |
| SGST 9% | 12,600.00 |
| **Total** | **165,200.00** |
| TDS (Sec 393 prof. services, 10% of 140,000) | −14,000.00 |
| **Net receivable** | **151,200.00** |

### 21.2 Same invoice, customer in Maharashtra (27)
Taxable 140,000 → **IGST 18% 25,200** → total 165,200 (no CGST/SGST).

### 21.3 Export of services under LUT
Customer overseas, LUT valid → IGST 0%, total = 140,000, note "Supply meant for export under LUT
without payment of IGST". Reported in GSTR-1 EXP (without payment). Currency USD with exchange rate
snapshot; ledgers in INR.

### 21.4 Reverse charge
Category flagged RCM for the recipient → taxes listed with behaviour `reverse_charge`
(e.g. IGST 18% 25,200 "payable by recipient"), **total = 140,000**, note "Tax payable on reverse charge".

### 21.5 Payment with TDS
Invoice total 165,200. Customer pays ₹151,200 by NEFT and deducts TDS ₹14,000 (10% on 140,000):
allocation `cash 151,200 + tds 14,000` → invoice **paid**; `tds_receivable 14,000` status `expected`
until it appears in Form 26AS for that quarter.

### 21.6 Partial credit note
Invoice above (intra-state, 18%). Service deficiency credit of ₹10,000 taxable → copies the original
treatment: CGST 900 + SGST 900 → note total 11,800; original `credited_amount = 11,800`,
`balance_due = 153,400` (if unpaid). Status stays `issued`/`partially_paid` — never "paid" because of
a credit.

### 21.7 Rate change boundary
Category `GOODS_12` (old slab) retired on 2025-09-22, mapped to `GOODS_5`. Invoice dated 2025-09-21 →
12%; dated 2025-09-22 → 5%. A credit note in October against the September-21 invoice still uses 12%.

### 21.8 Compound tax (Canada-style, to prove the model)
GST 5% on 1,000 = 50; QST (old rule) 9.975% on 1,050 (`base = taxable_plus_previous`) = 104.74;
total 1,154.74.

---

## 22. Glossary

| Term | Meaning |
|---|---|
| GSTIN | 15-character GST registration number; first 2 digits = state code |
| CGST / SGST / UTGST / IGST | Central / State / Union-territory / Integrated GST |
| Place of supply (PoS) | State whose tax applies; decides intra vs inter-state |
| HSN / SAC | Classification codes for goods / services |
| LUT | Letter of Undertaking — allows zero-rated exports/SEZ supplies without paying IGST |
| SEZ | Special Economic Zone — supplies to SEZ are zero-rated |
| RCM | Reverse charge mechanism — recipient pays the GST |
| IRP / IRN | Invoice Registration Portal / Invoice Reference Number (e-invoicing) |
| GSP | GST Suvidha Provider — intermediary API for IRP/GSTN |
| AATO | Aggregate annual turnover (e-invoice thresholds) |
| GSTR-1 | Monthly/quarterly outward-supplies return |
| TDS | Tax deducted at source (income tax), withheld by the payer |
| TCS | Tax collected at source, collected by the seller |
| GST-TDS | 2% GST withheld by government buyers (s.51 CGST Act) |
| Form 26AS / 16A | Government statement / deductor certificate showing TDS credited to you |
| TAN | Deductor's tax deduction account number |
| Proforma | Pre-invoice request for payment; not a tax document |
| Receipt voucher | GST document for an advance received for services |

---

## 23. Sources

Research done 2026-10-05; **re-verify rates, thresholds and section numbers before seeding** — they
change by notification.

- GST 2.0 slabs and cess removal (effective 22 Sep 2025):
  [PIB – GST Reforms 2025](https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/sep/doc202594628401.pdf),
  [Tally – New GST rates Sept 2025](https://tallysolutions.com/gst/new-gst-rates-september-2025-business-impact/),
  [India Briefing – compensation cess removal](https://www.india-briefing.com/news/gst-cess-removal-india-2025-business-benefits-39879.html/),
  [Kotak – GST 2.0](https://www.kotakmf.com/Information/blogs/gst-2-point-0)
- TDS under the Income-tax Act 2025 (Section 393, payment codes, from 1 Apr 2026):
  [ClearTax – TDS/TCS changes from April 2026](https://cleartax.in/s/tds-and-tcs-changes-from-april-2026),
  [TaxGarden – old vs new section numbers](https://taxgarden.in/blog/income-tax-act-2025-section-393-tds-new-numbers-old-194c-194j-194q),
  [Terra Insight – Section 393 payment codes](https://www.terra-insight.com/resources/section-393-payment-code-reference/),
  [Wikipedia – Income-tax Act, 2025](https://en.wikipedia.org/wiki/Income-tax_Act,_2025)
- No TDS on the GST component (CBDT Circular 23/2017):
  [ClearTax – No TDS on GST](https://cleartax.in/s/no-tds-on-gst),
  [Terra Insight – TDS on GST component under s.393](https://www.terra-insight.com/insights/tds-on-gst-component-india/)
- E-invoicing thresholds and 30-day rule:
  [Tally – e-invoicing rules 2026](https://tallysolutions.com/accounting/e-invoicing-rules-in-india/),
  [IndiaFilings – 30-day rule](https://www.indiafilings.com/learn/gst-einvoice-30-day-rule-10crore-turnover),
  [BUSY – IRN generation/cancellation](https://busy.in/gst/all-about-invoice-reference-number-irn/)
- Invoice rules (Rule 46) and credit notes (s.34):
  [TaxGuru – Section 31 / Rule 46](https://taxguru.in/goods-and-service-tax/tax-invoice-requirements-section-31-cgst-act-gst-rule-46.html),
  [Taxilla – credit notes under GST](https://www.taxilla.com/credit-note-gst-compliance-guide)
- Tax engine modelling:
  [Odoo tax management guide](https://theledgerlabs.com/odoo-tax-management-guide/),
  [Stripe – tax codes and tax behavior](https://docs.stripe.com/tax/products-prices-tax-codes-tax-behavior),
  [Stripe – tax rates](https://docs.stripe.com/tax/tax-rates)
- FBOS API reference (billing section, `InvoiceDraftCreate`, `Invoice`, `EInvoice`, `PaymentCreate`):
  `~/Projects/fbos-api-reference.html`

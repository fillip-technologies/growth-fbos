# Company Tax & Finance — Research and Money-Flow Map

> Status: **research only, nothing built.** Written 2026-10-09.
> Companion to [`tax-and-billing-plan.md`](tax-and-billing-plan.md). That document designs the
> quote-to-cash engine (sales side). This one widens the lens: **every tax a company touches, and
> how money moves through the company** — in, out, and to the government.
> Jurisdiction: **India**. Assumed entity: a private limited company selling **services and some
> products**, with employees, vendors/freelancers, and possibly foreign clients.

## How to read the confidence markers

| Marker | Meaning |
|---|---|
| ✅ | Confirmed by two or more web sources (all secondary — tax-blog / vendor sites, not the statute) |
| ⚠️ | Sources disagree, or only one source, or the rule changed recently — **verify with a CA / the official notification** |
| 🧠 | From general knowledge, not re-checked in this research pass |

None of the sources were the Act, CBIC notifications or TRACES themselves. Treat every rate and
threshold as **seed data to be verified by a chartered accountant before it is used to charge,
deduct or file anything.** This is research, not tax advice.

---

## Table of contents

1. [The big picture: which taxes exist and who they hit](#1-the-big-picture)
2. [GST — indirect tax on supply](#2-gst)
3. [TDS and TCS — tax collected on the way](#3-tds-and-tcs)
4. [Income tax on the company](#4-income-tax-on-the-company)
5. [Payroll statutory](#5-payroll-statutory)
6. [Other levies and regulatory finance](#6-other-levies-and-regulatory-finance)
7. [Money flow through the company](#7-money-flow-through-the-company)
8. [Worked examples with numbers](#8-worked-examples)
9. [Compliance calendar](#9-compliance-calendar)
10. [Accounting view: ledgers the flow must post to](#10-accounting-view)
11. [What this means for FBOS](#11-what-this-means-for-fbos)
12. [Open questions for the business](#12-open-questions)
13. [Glossary](#13-glossary)
14. [Sources](#14-sources)

---

## 1. The big picture

Taxes that touch a company fall into **five buckets**. The key mental model: GST and TDS are
mostly **other people's money passing through the company's bank account**; income tax is the
company's **own** cost.

| Bucket | Taxes | Whose money? | Company's role | Cost to company? |
|---|---|---|---|---|
| **Indirect – on supply** | GST (CGST, SGST/UTGST, IGST, cess), customs duty on imports | The **customer's** (added on top of price) | Collector → pays to govt after setting off credit | No (if credit is eligible) — otherwise yes |
| **Withholding – on payments out** | TDS (on vendor, freelancer, rent, salary, foreign payments), GST-TDS (if govt body) | The **payee's** income tax, held back | Deductor → deposits to govt | No |
| **Withholding – on payments in** | TDS deducted by customers from what they pay us; TCS on certain sales | **Ours**, held back by others | Receiver of reduced cash; later claims credit | No — it is a prepayment of our income tax |
| **Direct – on profit** | Corporate income tax, MAT/AMT, advance tax, surcharge, cess | **Company's own** | Taxpayer | **Yes** |
| **Payroll & local** | PF, ESI, professional tax, labour welfare fund, gratuity, TDS on salary | Part employee's, part employer's | Collector + payer | Employer share is a cost |

```
                         ┌──────────── GOVERNMENT ────────────┐
                         │  GST   TDS   Income tax   PF/ESI/PT │
                         └──▲───────▲────────▲──────────▲──────┘
                            │       │        │          │
   Customers ──pay──► [ COMPANY BANK ] ──pays──► Vendors / Employees / Landlord / Govt
              (price + GST − TDS they held)   (net of TDS we held; plus statutory dues)
```

---

## 2. GST

### 2.1 Components ✅

| Component | Charged when | Who gets it |
|---|---|---|
| **CGST** | Supplier and place of supply in the **same state** | Centre |
| **SGST** | Same as above | The state |
| **UTGST** | Same-UT supply where the UT has no legislature (e.g. Chandigarh, Lakshadweep) — replaces SGST | The UT |
| **IGST** | Supplier and place of supply in **different states**; also imports; exports/SEZ when charged | Centre, apportioned to the destination state |
| **Cess** | Specific demerit goods only | Centre (scrapped for most goods in 2025) |

Intra-state: tax splits **half CGST + half SGST**. An 18% supply → 9% + 9%. Inter-state: **18% IGST**,
never CGST+SGST. The total is the same; only the *bucket* differs, which matters for credit
utilisation and for which government receives the money.

### 2.2 Rates — GST 2.0 (effective 22 Sep 2025) ✅

- The 56th GST Council meeting (3 Sep 2025) replaced the four slabs 5/12/18/28 with a simple
  structure: **5% and 18%** as standard rates, a **40%** rate for luxury/"sin" goods, and **0%/exempt**
  for essentials.
- About 90% of items previously at 28% moved to 18%; almost all of the 12% items moved to 5%.
- Most **software / IT / consulting / professional services remain at 18%** 🧠 — confirm the SAC
  heading for each offering, as some services have specific entries.
- Because rates changed on a date, **the rate to apply depends on the time of supply**, not on the
  date someone opens the screen. Rates are effective-dated data, never constants.

### 2.3 Which tax applies — supply-type matrix 🧠 (backed by the Place-of-Supply rules, IGST Act ss.10, 12, 13)

| Supply type | Tax shown on invoice | Notes |
|---|---|---|
| B2B, same state | CGST + SGST | |
| B2B, other state | IGST | |
| B2C, same state | CGST + SGST | Unregistered buyer; goes to GSTR-1 B2C buckets |
| B2C, other state | IGST | Large-value inter-state B2C reported separately |
| **Export of services** (recipient outside India, payment in convertible foreign exchange, etc.) | **0% IGST** under **LUT** (no tax paid), *or* IGST paid and refund claimed | Zero-rated, not exempt — input credit stays alive |
| **Export of goods** | Same LUT-or-pay choice; shipping bill / customs filings | |
| **Supply to SEZ unit / developer** | Zero-rated, same LUT/pay choice | Needs SEZ endorsement |
| **Reverse charge (RCM)** | Invoice shows tax "payable on reverse charge"; the **buyer** pays | See §2.5 |
| **Exempt / nil-rated / non-GST** | No tax; reported separately | Blocks proportionate input credit |
| **Composition supplier** | Cannot charge GST; issues *bill of supply* | Only relevant if *we* opt for composition |

**Place of supply for services** ⚠️ (default rule 🧠): for a registered recipient it is generally the
recipient's registered location; for an unregistered recipient it is the address on record. Special
rules exist for immovable property, events, restaurants, transport, etc. The system needs a
**`place_of_supply` override** on every document, not only a state-vs-state compare.

### 2.4 Time of supply and invoice rules

- **GST is due on the invoice, not on payment received.** If the company invoices ₹1,00,000 and the
  client pays ₹50,000, GST is still owed on the whole invoice. Staging invoices or using proforma +
  receipt vouchers is how companies align tax with cash — see [§7.7](#77-partial-payment-the-100000-invoice-and-50000-received) ✅.
- **Services:** the tax point is the earlier of invoice date / payment date (subject to the 30-day
  invoicing window). **GST on advances for services is payable when the advance is received** 🧠 —
  a *receipt voucher* must be raised and later adjusted against the invoice. For goods, advances
  carry no GST.
- **Invoice (Rule 46)** — consecutive serial, **≤ 16 characters**, unique per FY, with supplier and
  recipient GSTIN, place of supply, HSN/SAC, per-component tax, RCM flag. Details in the
  [billing plan §3.1](tax-and-billing-plan.md#31-gst-india).
- **E-invoicing** — mandatory above **₹5 crore** aggregate turnover; from ₹10 crore must be reported
  within **30 days** of the invoice date. IRN cancel window: 24 h. ⚠️ thresholds have been lowered
  repeatedly; check the current one.
- **Credit notes (s.34)** — only way to reduce an issued invoice; deadline **30 Nov after the FY**
  of the original supply.

### 2.5 Reverse charge (RCM) ✅ partial

Normally the supplier collects GST. Under RCM the **recipient** self-assesses and pays it. For a
services company the practical cases are the *purchases* it makes:

| Purchased from | RCM? | Note |
|---|---|---|
| **Advocate / law firm** (legal services to a business) | **Yes** | Company pays the GST itself |
| **GTA** (goods transport agency) | **Yes**, unless the GTA charged forward-charge GST | GTA charges 5% without credit or 12%→18%-era rates with credit ⚠️ re-check after GST 2.0 |
| **Director's fees / sitting fees** | **Yes** | |
| Sponsorship services, arbitral tribunal, insurance agent, recovery agent, copyright transfer | **Yes** | |
| **Purchases from unregistered suppliers** | Mostly suspended for ordinary goods/services 🧠 — only notified categories (e.g. certain builder / agriculture cases) | ⚠️ |
| **Import of services** (foreign vendor with no Indian GST registration) | **Yes** — pay **IGST** under RCM | Common for SaaS, cloud, ads, freelancers abroad |

RCM mechanics: the company **pays the tax in cash** (not from credit ledger), reports it in
GSTR-3B, and *then* takes the same amount as input credit (if eligible). Net P&L cost is zero but
**cash goes out first**. This is the most commonly missed cash-flow item.

### 2.6 Input Tax Credit (ITC) ✅

ITC is the GST the company paid on its own purchases; it is subtracted from the GST it collected.
Conditions (s.16), **all** required:

1. Registered person, using the purchase for business
2. Valid tax invoice / debit note
3. Goods or services actually received
4. **Supplier has filed their return and paid** — invoice visible in the buyer's **GSTR-2B**
5. Buyer's own return filed; claimed within the statutory time limit (s.16(4))
6. Supplier paid within **180 days** or ITC is reversed with interest ⚠️

**Blocked credits (s.17(5))** — GST paid is a real cost: motor vehicles for ≤13 persons (exceptions
for vehicle dealers / transport / driving school), food & beverages / outdoor catering, health and
life insurance for staff (exceptions apply), construction of immovable property, personal
consumption, gifts. ✅ partial, ⚠️ details.

**Mixed use:** if the company makes both taxable and exempt supplies, ITC must be apportioned
(Rule 42/43) 🧠.

**ITC utilisation order** 🧠 (important for the ledger design):

```
IGST credit  → first against IGST payable, then CGST, then SGST
CGST credit  → against CGST, then IGST   (never SGST)
SGST credit  → against SGST, then IGST   (never CGST)
Any shortfall → paid in CASH from the electronic cash ledger
```

The government keeps three **credit** ledgers (IGST/CGST/SGST) and a **cash ledger** per
registration. The company's books should mirror that.

### 2.7 Returns and payment ✅

| Return | What | Due (regular monthly filers, turnover > ₹5 cr) | QRMP (≤ ₹5 cr) |
|---|---|---|---|
| **GSTR-1** | Outward supplies | 11th of next month | Quarterly, 13th of month after quarter |
| **GSTR-3B** | Summary + **tax payment** | 20th of next month | Quarterly, 22nd/24th (state group) |
| **PMT-06** | Monthly tax deposit (QRMP only) | — | 25th |
| **GSTR-2B** | Auto-generated inward-supply statement (credit eligibility) | Generated ~14th | |
| **GSTR-9 / 9C** | Annual return / reconciliation | 31 Dec after FY (9C above ₹5 cr) 🧠 | |

- Late fee: ₹50/day (₹25 CGST + ₹25 SGST) for ordinary returns, ₹20/day for nil returns, with
  turnover-based caps. **Interest: 18% p.a.** on tax paid late, computed on the cash portion. ✅
  Wrongly claimed and used ITC attracts a higher rate (24% in some sources, 18% in others) ⚠️.
- There is a new bar on filing very old returns (3-year bar) ⚠️.

### 2.8 Registration 🧠

- Mandatory above ₹20 lakh annual turnover for services (₹40 lakh goods; ₹10 lakh for special-category
  states), regardless of turnover for inter-state taxable supply of services (limited exceptions),
  e-commerce sellers, RCM-liable persons, etc.
- **One GSTIN per state** where the company operates. A multi-state company has several GSTINs
  under one PAN; each is a separate compliance and invoice-series unit. Branch-to-branch supply
  between GSTINs is a taxable supply.

### 2.9 GST-TDS and GST-TCS 🧠

- **GST-TDS (s.51):** government departments / PSUs deduct 2% (1%+1% or 2% IGST) from payments above
  ₹2.5 lakh. Appears in the supplier's electronic cash ledger.
- **GST-TCS (s.52):** e-commerce operators collect 0.5% (reduced from 1%) on net supplies made through
  them.

---

## 3. TDS and TCS

### 3.1 Two directions of the same mechanism

| Direction | Who is the deductor | Cash effect on us | Accounting |
|---|---|---|---|
| **TDS we deduct** (outflow side) | **We** — on payments to vendors, freelancers, landlords, employees, foreign parties | We pay the payee *less* and owe the difference to govt | **TDS payable** (liability) → cleared on challan deposit |
| **TDS others deduct** (inflow side) | **Our customers** — on what they pay us | We receive *less* than the invoice | **TDS receivable** (asset) → matched to Form 26AS/AIS, then offset against our income tax |
| **TCS we collect** | We — on certain sales (liquor, scrap, timber, motor vehicles >₹10 L, overseas tours, LRS remittance by banks…). Rare for a services company. | We collect *extra* from buyer | **TCS payable** |

TDS never changes the invoice total. It is **a part-payment of income tax, taken early**.

### 3.2 Income-tax Act 2025 renumbering ✅ (⚠️ details)

The Income-tax Act, 2025 replaced the 1961 Act **from 1 April 2026**. Practical consequences:

- Salary TDS → **Section 392**; nearly everything else (old 194C, 194J, 194H, 194I, 194Q, 195…) →
  **Section 393**, with **payment codes** (1001–1092 range) instead of section letters. TCS → **s.394**.
- The Act applicable to a transaction depends on the **earlier of credit-or-payment date**. On or
  before 31 Mar 2026 → old Act and codes; on or after 1 Apr 2026 → new Act. Returns with the wrong
  reference are rejected by the portal.
- Rates and thresholds were **largely carried over**; the structure changed. Form numbers (24Q, 26Q,
  27Q) have been renamed too ⚠️ — check the current utility.

### 3.3 TDS rate table — payments we make (resident payees)

Codes and rates per the 2026-27 secondary sources; thresholds as stated there. ⚠️ **verify against
the Act/TRACES before seeding.**

| Nature of payment | Old section | New (s.393 payment code) | Rate | Threshold |
|---|---|---|---|---|
| Salary | 192 | s.392 | Slab rate (employee's regime) | Basic exemption |
| Contractor / sub-contractor — individual or HUF | 194C | 1023 | **1%** | ₹30,000 single / ₹1,00,000 yearly |
| Contractor — company, firm, others | 194C | 1024 | **2%** | same |
| **Professional fees** (lawyer, CA, consultant, architect, doctor…); royalty (non-film) | 194J(b) | 1027 | **10%** | ₹50,000/yr |
| **Technical services**, call-centre, film royalty | 194J(a) | 1026 | **2%** | ₹50,000/yr |
| Director's fees (non-salary) | 194J | 1028 | 10% | none |
| Commission / brokerage | 194H | 1006 | **2%** (cut from 5% on 1 Oct 2024) | ₹20,000/yr |
| Rent — plant, machinery, equipment | 194I(a) | 1008 | **2%** | ₹50,000/month |
| Rent — land, building, furniture | 194I(b) | 1009 | **10%** | ₹50,000/month |
| Purchase of goods (buyer turnover > ₹10 cr) | 194Q | 1031 | **0.1%** on amount above ₹50 lakh/yr | ₹50 lakh |
| Interest (non-bank) | 194A | — | 10% | ₹50,000 (raised in Budget 2025) |
| E-commerce operator → seller | 194-O | in s.393 | 0.1% | ₹5 lakh/seller 🧠 |
| Perquisite / benefit to business associate | 194R | — | 10% | ₹20,000 🧠 |
| Payment to non-resident | 195 | in s.393 | **As per Act / DTAA** | none — see §3.6 |
| No / invalid PAN of payee | 206AA | s.397(2)? | **20%** or higher of applicable ⚠️ | — |

**Key judgement calls for each vendor payment:**

1. **Classify the payment** (professional vs technical vs contract vs commission) — the same freelancer
   can be 10% or 2% depending on the work. Wrong choice → short deduction → interest + disallowance.
2. **Base excludes GST** if GST is shown separately on the invoice (CBDT Circular 23/2017). ✅
3. **Threshold tracking** is per payee per year, so the system must keep cumulative payments per
   PAN per section.
4. **Lower/nil deduction certificate** (s.197) lets a payee have a reduced rate for a period and cap.
5. **Time of deduction** is the *earlier* of credit to the payee's account (booking the bill) or
   payment. Booking the invoice triggers TDS even if cash goes out next month. 🧠

### 3.4 TDS on payments we receive (customers deduct from us)

- Customer pays us `invoice total − TDS`. We book **TDS receivable** for the held amount.
- It is real money owed to us **by the government**, only realised when:
  1. the customer deposits it **and** files their TDS return, so it appears in our **Form 26AS / AIS**; and
  2. we claim it against our annual income tax (or it is refunded if it exceeds liability).
- Risks: customer deposits late or under a wrong PAN → credit never shows; customer deducts at a
  higher rate than the law needs (e.g. 10% where 2% applies) → excess is locked up until refund.
- Keep: customer TAN, section/code, rate, amount, certificate (Form 16A/equivalent), quarter, and a
  `matched_to_26AS` flag. (Design is in [billing plan §11](tax-and-billing-plan.md#11-payments-tds-and-receivables).)

### 3.5 Deposit, returns, interest ✅

| Event | Deadline |
|---|---|
| Deposit of TDS (non-government deductor) | **7th of the next month** (30 April for March deductions) |
| Quarterly TDS statement | 31 Jul / 31 Oct / 31 Jan / 31 May (FY 2026-27 dates) |
| Certificate to payee | Quarterly/annual form within 15 days of the return deadline 🧠 |

| Default | Consequence |
|---|---|
| Not deducted (or short) | **1% per month** (or part) interest from the date it should have been deducted |
| Deducted but not deposited | **1.5% per month** (or part) from the date of deduction; prosecution risk |
| Late statement | ₹200/day fee, capped at the TDS amount (s.234E in the old Act; ⚠️ re-numbered) |
| Wrong/missing statement | Penalty ₹10,000–₹1,00,000 (s.271H) |
| Non-deduction → expense | **30% of the expense disallowed** as a deduction when computing our profit 🧠 |

### 3.6 Payments abroad (s.195 / DTAA) 🧠⚠️

Payments to non-residents (SaaS, cloud, foreign contractors, ads):

- **TDS at the section's rate or the treaty rate**, whichever is lower, with a Tax Residency
  Certificate and Form 10F from the payee.
- Compliance forms: **15CA / 15CB** (CA certificate) before remittance. Banks refuse to remit without them.
- Also: **IGST under RCM** on imported services (§2.5); **equalisation levy** and FEMA rules may apply
  to some digital services.
- Many "software subscription" payments are *not* taxable in India as royalty depending on the
  facts — this is a genuine CA decision, not a lookup.

---

## 4. Income tax on the company

### 4.1 Rates (domestic company) ✅

| Regime | Base rate | Effective with surcharge+cess | Notes |
|---|---|---|---|
| **s.115BAA** (concessional) | **22%** | ≈ **25.17%** (10% flat surcharge + 4% cess) | Must forgo most exemptions/deductions and **MAT credit**; election is **irrevocable**; no MAT |
| **s.115BAB** (new manufacturing) | 15% | ≈ 17.16% | Only new manufacturing companies; ⚠️ sunset/eligibility, verify if still open |
| **Normal regime** | 25% (turnover ≤ ₹400 cr) / 30% (above) | + surcharge 7–12% + 4% cess | Keeps deductions; **MAT** applies |
| **MAT** | 15% of book profit | + surcharge + cess | Not applicable under 115BAA/BAB ✅ |
| Foreign company | 35% (reduced from 40%, FY 2024-25) | ⚠️ conflicting sources | |

Most small/mid service companies choose **s.115BAA**. This is a one-way decision made with the
return.

### 4.2 How profit is computed 🧠

```
Revenue (excl. GST)
 − Operating costs (salaries, vendors, rent, software, travel…)   [only deductible if TDS rules were followed]
 − Depreciation (income-tax rates; separate from book depreciation)
 − Other allowable items (bad debts written off, interest, etc.)
 ± Disallowances (s.40(a)(ia) TDS default, s.43B(h) late MSME payments, personal expenses…)
 = Taxable income
 × Rate  = Tax
 − Advance tax paid − TDS received − TCS − MAT credit
 = Tax payable / refund
```

### 4.3 Specific disallowance traps

- **s.43B(h) — MSME vendors.** Amounts owed to **micro and small** enterprises beyond **45 days** (15 if
  no written agreement) are disallowed in the year, allowed only when actually paid. It is a *timing*
  loss, not permanent. ✅ In the 2025 Act this is reported as **s.37(2)(g)** ⚠️. Needs each vendor's
  **Udyam registration** to be stored. A vendor master with an "MSME class" field is a real tax control.
- **s.40(a)(ia) — non-deduction of TDS.** 30% of the expense is disallowed. 🧠
- **Cash payments over ₹10,000/day** to one person are disallowed 🧠.
- **Related-party / transfer pricing** documentation if the company deals with foreign group entities 🧠.

### 4.4 Advance tax ✅

Companies pay estimated tax in four instalments **15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar
(100%)**, cumulative. A shortfall earns interest (1% per month or part). Pay by challan; it plus TDS
receivable are the credits against the final bill.

### 4.5 Annual filings 🧠⚠️

| Filing | Typical deadline |
|---|---|
| Tax audit report (Form 3CA/3CD → renamed) | 30 Sep (if turnover > ₹1 cr / ₹10 cr where 95% digital, etc.) |
| ITR for company | 31 Oct (audit cases); 30 Nov if transfer pricing |
| Companies Act: AGM | within 6 months of FY end (30 Sep) |
| ROC: AOC-4 (financials) / MGT-7 (annual return) | 30 days / 60 days from AGM |

### 4.6 Fixed assets and depreciation 🧠

Laptops, servers, furniture are capitalised, not expensed. Tax depreciation uses **block-of-assets**
rates (e.g. computers 40%); the Companies Act uses useful-life rules. The two differ, creating
**deferred tax**. GST input credit is available on capital goods unless blocked (§2.6).
`09_assets` is the natural source for the asset register.

---

## 5. Payroll statutory

Salary is the largest outflow for most service companies, and it has the most tax-like layers.

| Item | Employee pays | Employer pays | Notes |
|---|---|---|---|
| **TDS on salary** (s.192 → s.392) | Yes, per slab, monthly | Deducts & deposits by 7th | Based on employee's chosen regime; Form 16 yearly |
| **EPF** | 12% of wages | 12% of wages (of which 8.33% to pension scheme EPS, capped on ₹15,000 ceiling) | ✅ ceiling ₹15,000 for EPS; verify current ⚠️ |
| **EDLI / admin charges** | — | ≈0.5% + admin ✅ (EDLI 0.5%) | |
| **ESI** | **0.75%** | **3.25%** | Wage ceiling ₹21,000/month ✅ ⚠️ |
| **Professional tax** (state) | ₹200–₹2,500/yr slab by state | Employer deducts and deposits | e.g. Karnataka ₹200/mo from ₹25,000 gross; Maharashtra ₹175–₹200, ₹300 in Feb (annual ₹2,500) ⚠️ state-specific |
| **Gratuity** | — | Provision ≈ 4.81% of basic; paid after 5 yrs (1 yr for fixed-term under the new codes) | ⚠️ Social Security Code transition |
| **Labour Welfare Fund** | Small | Small | State-specific 🧠 |
| **Bonus** | — | Min 8.33% (if applicable) | 🧠 |

**Labour codes (notified effective 21 Nov 2025) ✅:** a uniform "wages" definition under which basic
pay must be **≥ 50% of total remuneration**. This enlarges the PF / gratuity / bonus base, so
payroll cost rises even if CTC is unchanged. Central/state rules were still being finalised through
2026 ⚠️.

**Cash timing:** the company deducts employee share of PF/ESI/PT/TDS from salary at month-end and
deposits them early next month (PF/ESI by the 15th, TDS by the 7th, PT per state). The net-salary
payment and the statutory payments are therefore **separate outflows on different dates**.

**Reimbursements and perquisites:** some are tax-free for the employee, but may attract GST (e.g.
staff food) or TDS under 194R when given to non-employees. 🧠

---

## 6. Other levies and regulatory finance

| Item | What it is | Relevance |
|---|---|---|
| **Customs duty (BCD + IGST on import)** | On imported goods (equipment, products to resell) | Paid at port; the IGST part is creditable. Needs a Bill of Entry. Relevant only if the company imports goods |
| **Stamp duty** | State levy on contracts, agreements, share transfers | Small cost; agreements must be stamped to be admissible 🧠 |
| **Foreign exchange (FEMA / RBI)** | Export receipts via an AD bank get an **FIRC/e-FIRC**; payments abroad need 15CA/15CB | Needed to prove "export of service" for zero-rating |
| **Companies Act** | Statutory audit, ROC filings, director KYC | Not tax but cash outflow (auditor fees) |
| **Equalisation levy** | On certain foreign digital ad payments | Rare; ⚠️ status has changed 🧠 |
| **Local/municipal** | Trade licence, property tax, shop-establishment | Small 🧠 |
| **Securities / TCS on LRS** | Not company-level | n/a |

---

## 7. Money flow through the company

### 7.1 The four flows

1. **Revenue inflow** — customers pay (cash/bank), net of what they withhold.
2. **Operating outflow** — vendors, freelancers, rent, SaaS, travel, assets.
3. **People outflow** — net salary + statutory deposits.
4. **Tax flow** — GST, TDS, advance tax, PF/ESI/PT, and the claims coming back (ITC, TDS credit, refunds).

### 7.2 Quote to cash (sales side) — where each tax appears

```
Quotation ──► Contract ──► Billing schedule
   (price + estimated GST shown)       │
                                       ▼
                        Advance received? ──► Receipt voucher (GST due now, services only)
                                       │
                                       ▼
   Tax invoice:   Taxable value        100,000
                  + CGST 9% / SGST 9%  (or IGST 18%)  18,000
                  = Invoice total      118,000        ◄── books: Revenue 100,000, GST payable 18,000, Receivable 118,000
                                       │
                                       ▼
   Customer pays:  Bank receives       108,000        (118,000 − TDS 10,000 at 10%)
                   TDS withheld         10,000        ◄── books: TDS receivable (govt owes us)
                   GST-TDS withheld (govt customers only)
                                       │
                                       ▼
   Government repays TDS credit: shows in 26AS ──► adjusted against our income tax
```

> If the customer pays only **part**, GST on the full invoice is still due — see
> [§7.7](#77-partial-payment-the-100000-invoice-and-50000-received) for what companies do about it.

**Receivable ≠ cash.** The collections team should chase only what the customer genuinely still owes:
`gross balance − expected TDS`. If we chase the TDS portion we annoy customers; if we ignore it, our
receivable never closes. (Handled in the [billing plan](tax-and-billing-plan.md).)

### 7.3 Procure to pay (purchase side) — mostly absent from the existing plan

```
Vendor invoice/bill received
   ├─► Verify: vendor GSTIN valid? appears in GSTR-2B? MSME class? PAN present?
   ├─► Classify: professional / technical / contract / rent / goods / capital asset / foreign
   ├─► Compute:   TDS to deduct (section, rate, threshold, cumulative)
   │              GST input credit eligible? blocked? RCM payable by us?
   ▼
Book the bill:  Expense (excl. GST)          Dr  50,000
                Input GST (eligible)         Dr   9,000
                  Vendor payable                    Cr  54,000   (50,000 + 9,000 − 5,000 TDS)
                  TDS payable                       Cr   5,000
   ▼
Pay vendor net 54,000  ──►  Deposit TDS 5,000 to govt by the 7th of next month
   ▼
File TDS statement; issue certificate to vendor
```

The vendor bill is where **most of a company's tax mistakes happen**: wrong TDS section, missed
RCM, ITC claimed on a blocked item or on an invoice the supplier never reported, MSME dues left
beyond 45 days.

### 7.4 Pay-to-government (monthly cycle)

```
Output GST collected   (CGST/SGST/IGST from sales invoices + RCM self-assessed)
 − ITC available       (from GSTR-2B, eligible only)
 = Net GST payable ──► GSTR-3B by the 20th → cash from bank to govt
                       (IGST credit first on IGST, then CGST, SGST — §2.6)

TDS deducted from vendors/employees/rent  ──► challan by the 7th of next month
PF, ESI                                    ──► by the 15th
Professional tax                           ──► per state schedule
Advance tax                                ──► 15 Jun / Sep / Dec / Mar
```

### 7.5 Where the money actually sits at any moment

| Pot | What it is | Is it the company's money? |
|---|---|---|
| Operating cash | Bank balance | Partly. Includes tax collected not yet deposited |
| **GST payable (collected)** | GST charged to customers, not yet paid | **No** — held in trust; commingled with cash |
| **TDS payable** | Held back from vendors/employees | **No** |
| **PF/ESI/PT payable** | Employees' share deducted | **No** |
| Receivables (net of TDS) | Customers owe us | Yes |
| **TDS receivable** | Govt owes us | Yes, but locked until claimed |
| **ITC balance** (in govt ledger) | Credit we can use to pay future GST | Yes, but non-cash |
| Advance tax paid | Prepaid income tax | Yes, until set off |

A common cash-flow trap: the bank balance looks healthy but **a third of it is GST + TDS + PF owed
to government.** A finance dashboard should show *"free cash" = bank − tax liabilities due in the
next 30 days.*

### 7.6 Cash vs accrual

Accounting is on **accrual** (booked on invoice), but several tax obligations are **cash-triggered**
(TDS at the earlier of credit/payment, GST on advances, 43B(h) at year-end balances). The system
needs both a **book date** and a **cash/tax point date** on every document.

### 7.7 Partial payment: the ₹1,00,000 invoice and ₹50,000 received

A common assumption is: *"company bills ₹1,00,000, client pays ₹50,000, client gets an invoice and
bill for the ₹50,000 paid, and the company pays government tax only on ₹50,000."* That is **not how
GST works** — the tax follows the **invoice, not the cash**. The way companies actually get the
result they want is by **choosing what to invoice**, not by taxing the payment.

**The rule (CGST s.13, services) ✅:** the time of supply is the **earliest** of (a) invoice date,
if issued within the 30-day window, or (b) date payment is received. The supply is treated as made
"to the extent covered by the invoice or the payment". So a tax invoice for ₹1,00,000 puts GST on
the **full** ₹1,00,000 in that month's GSTR-3B, whether the client pays 0%, 50% or 100%.

**There is no GST relief for non-payment ✅.** A credit note under s.34 is allowed only for excess
value, returns, or deficient services — not for "client didn't pay". GST already paid on a bad
debt generally cannot be adjusted. ⚠️ Edge cases and the credit-note deadline differ between
sources; a CA must confirm a real case.

Real companies therefore take one of **four paths**. Numbers use ₹1,00,000 taxable + 18% GST =
₹1,18,000 total, client pays half.

| Path | What the company issues | GST due (and when) | What the client gets | Typical use |
|---|---|---|---|---|
| **A. Full tax invoice, partial payment** | Tax invoice ₹1,00,000 + ₹18,000 GST | **₹18,000 on the full invoice**, in the invoice month's return, even though only ~₹59,000 came in | Invoice for the full amount + a **payment receipt** (not a tax document) for the part paid; balance stays "due" | Fixed-price work already delivered; client simply pays slowly |
| **B. Bill in stages (milestone / part invoices)** ✅ best practice | Tax invoice **#1 for ₹50,000 + ₹9,000 GST** now; invoice #2 for the rest when its milestone/date arrives | **₹9,000 now**, ₹9,000 later — matches cash if each invoice is paid on time | One invoice per stage, each with its own payment | Contracts with milestone, retainer or monthly billing; this is what the billing-schedule in the billing plan is for |
| **C. Proforma first, tax invoice on payment** | Proforma ₹1,18,000 (no GST liability, own series). Client pays ₹59,000 → company issues a **receipt voucher** for ₹59,000 (GST ₹9,000 due now); later issues the tax invoice and adjusts the advance | **₹9,000 on the advance** at receipt; balance GST when the final invoice/payment happens | Proforma → receipt voucher → tax invoice with the advance adjusted | Advance-heavy deals, new/untrusted clients |
| **D. Advance receipt for a service** | Receipt voucher at the time money lands | GST **on the advance** when received (services); **not** for goods | Receipt voucher, later superseded by the tax invoice | Any "pay half upfront" service |

Path B or C produces exactly what the user described in practice — "client pays ₹50,000, gets a
bill for that, company pays tax on ₹50,000" — but because the *document was written for the
₹50,000*, not because tax was computed on cash received.

**What path A looks like in money (the painful one):**

```
Month 1 (invoice issued):     GST on invoice booked  ₹18,000    (output liability)
Month 2, by the 20th:         GSTR-3B → pay ₹18,000 (less any ITC)  ◄── CASH OUT
Meanwhile cash received:      ₹59,000 − TDS ≈ ₹54,000
                              ₹59,000 still owed by client (includes ₹9,000 of the GST already paid)
```

The company has paid government ₹18,000 on money it has not fully collected. If the client never
pays, the company **has paid GST for nothing** and can't claim it back.

**Counter-pressure on the client:** if the client doesn't pay the supplier within **180 days** of the
invoice, it must **reverse the input credit it claimed, with 18% interest** (re-claimable on
payment) ✅. That is a genuine collections lever — GST-registered clients lose cash if they stall.

**Other taxes in the same scenario:**

| Tax | What it follows | Effect with ₹50,000 paid |
|---|---|---|
| **TDS by client** | Earlier of **credit** (booking the bill) or payment ✅ | Strictly, TDS arises on the full credited amount when the client books it. In practice many clients deduct on each payment (proportionately). Either way the client — not the company — decides and deposits; the company only records TDS **receivable** per receipt ⚠️ |
| **Company income tax** | Accrual (company books on mercantile basis) | **₹1,00,000 is income in the year invoiced**, even if unpaid. A bad debt is deductible only when written off, subject to conditions 🧠 |
| **Advance tax** | Estimated profit | Based on accrued income, so the company can owe tax on revenue it hasn't collected |
| **43B(h) / vendor side** | Not relevant to the client's payment | — |

**What this changes in the FBOS design:**

1. The invoice must be a **"what are we billing now?"** decision, not "everything". The billing
   schedule (milestone / % / dates) is how stage invoices are generated.
2. **Partial payments allocate to an invoice**, producing a **payment receipt** and an updated
   `balance_due`; they do **not** create a tax document (unless it is an advance with no invoice yet).
3. **Advance with no invoice** → **receipt voucher** with GST (services); later adjusted against the invoice.
4. Show finance a **GST-vs-cash gap** alert: "GST on invoices issued ₹X, cash actually collected ₹Y".
5. Store the **180-day** clock per invoice (customer's ITC reversal date) as a dunning trigger.
6. Credit notes are for corrections/returns/deficiency — **never as a bad-debt write-off**; keep a
   separate *write-off* entry (accounting only, no GST effect). This also fixes defect D4 in the billing plan.

### 7.8 Recommended FBOS flow: staged invoices from the billing schedule

**Decision.** Of the four paths in §7.7, FBOS adopts **B (staged invoices) as the default** and **D
(receipt voucher) as the fallback**. Path A (one big invoice, slow payer) is still possible but is
the exception the system warns about; path C (proforma) is an optional step *in front of* B.

**Why B wins**

| Criterion | B staged invoices | A full invoice | C proforma+voucher |
|---|---|---|---|
| GST paid vs cash collected | Closest match | Worst gap | Good, but more documents |
| Extra document types | None | None | Proforma **and** receipt voucher |
| Fits how contracts are written (advance / milestone / completion) | Directly | Poorly | Partly |
| Uses existing code | `ContractPaymentTerm`, `BillingSchedule(Line)` already exist | Current behaviour | New work |
| Client sees | One invoice per stage, each with its own payment | One invoice, part-paid | Three document types |
| Risk of tax error | Low | GST on uncollected money | Easy to forget the voucher/adjustment |

**The lifecycle**

```
Contract (agreed price + payment terms: e.g. 50% advance, 50% on completion)
   │
   ▼
Billing schedule generated from the terms
   line 1: Advance      50%   due on signing
   line 2: Completion   50%   due on delivery
   │
   │  each line becomes a DRAFT invoice only when it falls due
   ▼
[Optional] Proforma for the line  ── "please pay this", no GST liability, own number series
   │
   ▼
Finance reviews → ISSUE tax invoice for THAT LINE ONLY          ◄── GST liability starts here, for this line's amount
   │         (gapless number, tax lines frozen, e-invoice IRN if mandated)
   ▼
Client pays (full, or part) ── payment allocated to the invoice
   │         • bank receipt   • TDS client withheld (→ TDS receivable)   • short-pay / write-off
   │         • produces a PAYMENT RECEIPT (not a tax document)
   ▼
Invoice status: issued → partially_paid → paid       (credit note NEVER sets "paid")
   │
   ▼
Next schedule line falls due → repeat
```

**Fallback — money arrives before an invoice exists** (client wires an advance on their own):

```
Unallocated payment ──► Receipt voucher (GST due on the advance, services only)
                           │
                           ▼  when the matching schedule line is invoiced
                       Tax invoice issued ──► advance ADJUSTED against it (GST not paid twice)
```

**Rules the system enforces**

1. **Invoice only what is due.** An invoice can only be created from a schedule line (or an explicit
   ad-hoc line with a reason), never "the whole contract by default".
2. **One invoice per schedule line; a line is never billed twice.** The line stores `invoice_id`.
3. **Payments never create tax documents.** They create a receipt and change `balance_due`.
4. **Unallocated money gets a receipt voucher** (services) and is applied against the next invoice.
5. **Corrections only by credit/debit note**; a **write-off** is a separate accounting entry with no GST effect.
6. **Issued invoice is immutable**; tax lines stored as a snapshot.
7. **Warnings, not blocks:** "this invoice is > 30 days overdue", "GST liability on issued invoices
   ₹X vs cash collected ₹Y", "180-day input-credit-reversal date for the client is D".
8. **Invoice-issue deadline:** a service invoice must be issued within **30 days** of the service/milestone
   completion ✅; the schedule line carries a due date and the system flags lines approaching it.

**Timeline — ₹2,00,000 contract, 18% GST, 50/50 terms, client deducts 10% TDS**

| When | Event | Document | GST liability created | Cash in |
|---|---|---|---|---|
| Day 0 | Contract signed | Schedule: 2 lines | — | — |
| Day 1 | Line 1 due → invoice ₹1,00,000 + ₹18,000 GST | Tax invoice #1 (₹1,18,000) | **₹18,000** | — |
| Day 9 | Client pays ₹1,18,000 − TDS ₹10,000 | Payment receipt; TDS receivable ₹10,000 | — | ₹1,08,000 |
| Next month, ≤ 20th | Company files GSTR-3B | — | pays ₹18,000 (less ITC) | — |
| Day 60 | Work delivered → line 2 due | Tax invoice #2 (₹1,18,000) | **₹18,000** | — |
| Day 75 | Client settles ₹59,000 (half): pays ₹54,000 + holds ₹5,000 TDS | Receipt; invoice #2 `partially_paid`, balance ₹59,000 gross | — | ₹54,000 |
| Day 90 | Client still owes balance | Dunning on **net** owed (gross − expected TDS) | — | — |

At each point, GST paid roughly equals GST on money the company has actually invoiced for **work that was due**
— not on the entire contract up front. Only the *delivered-but-unpaid* part of invoice #2 is a gap.

**Journal postings per step (so the ledger design in §10 works):**

| Step | Dr | Cr |
|---|---|---|
| Issue invoice #1 | Accounts receivable 1,18,000 | Service revenue 1,00,000; Output CGST 9,000; Output SGST 9,000 |
| Client payment (₹1,08,000 + TDS ₹10,000) | Bank 1,08,000; TDS receivable 10,000 | Accounts receivable 1,18,000 |
| GSTR-3B payment | Output CGST/SGST 18,000 (less input credit) | Bank (cash portion) |
| Write-off of a stuck balance | Bad-debt expense | Accounts receivable (no GST entry) |

**What it needs in the build (extends the billing plan):**

- Wire `BillingScheduleLine → Invoice`: generate drafts on due date; mark line billed on issue.
- Payments: per-invoice allocation with a **per-allocation TDS** amount, section, rate (fixes defect D9).
- Receipt voucher document type + advance adjustment for the fallback.
- Optional proforma flow in front of a line.
- Dashboard: *GST issued vs cash collected*, and a *30-day invoicing window* alert.
- Collections list uses `balance_due − expected_TDS`.

**What still needs a CA / business decision**
(see §12): whether the company will ever invoice in full upfront (path A), whether to allow an
invoice before delivery for advances (B vs C), how TDS is handled when the client withholds on the
full credited amount rather than per payment, and the write-off policy.

---

## 8. Worked examples

### 8.1 Service invoice, intra-state, customer deducts TDS

Company (Karnataka) invoices a Karnataka company for consulting ₹1,00,000 (SAC 9983, GST 18%,
"professional" TDS 10%).

| Line | Amount (₹) |
|---|---|
| Taxable value | 1,00,000 |
| CGST 9% | 9,000 |
| SGST 9% | 9,000 |
| **Invoice total** | **1,18,000** |
| Customer's TDS @10% on 1,00,000 (GST excluded) | (10,000) |
| **Cash received** | **1,08,000** |

We owe GST of ₹18,000; if our own purchases carried ₹5,000 of eligible input credit the cash GST
is ₹13,000. The ₹10,000 TDS becomes a receivable from govt.

### 8.2 Same invoice, inter-state

Customer in Maharashtra: **IGST 18% = ₹18,000**, total unchanged at ₹1,18,000. Cash flow is
identical, but the credit is IGST.

### 8.3 Export of services

Invoice US customer $2,000 under LUT: **IGST 0%**, no GST collected, total = $2,000. No TDS (foreign
customer isn't an Indian deductor). Payment arrives in foreign exchange; the bank issues an FIRC.
ITC on our costs is still available (zero-rated), and any accumulated credit can be claimed as a refund.

### 8.4 Paying a freelancer

Freelance designer (individual, **no GST registration**) bills ₹50,000, a 'professional' service.

- Is it "technical" (2%) or "professional" (10%)? A CA's call; assume 10%.
- Threshold ₹50,000/yr → TDS applies (at the threshold, check cumulative).
- Pay ₹45,000; deposit ₹5,000 by the 7th of next month.
- No GST charged by the freelancer (below threshold); no RCM (ordinary service from unregistered
  supplier is not in the RCM list) 🧠. No ITC.

### 8.5 Paying a law firm

Legal fee ₹1,00,000 + GST under **RCM**.

- Law firm bills ₹1,00,000, no GST on the invoice.
- We pay ₹1,00,000 minus **TDS 10%** (₹10,000) = ₹90,000.
- We self-assess **GST ₹18,000** and pay it **in cash** with GSTR-3B; then claim ₹18,000 as ITC next
  month. Net cost: nothing, but ₹18,000 leaves the bank first.

### 8.6 Foreign SaaS vendor

US vendor charges ₹60,000 for a subscription.

- **IGST 18% under RCM**: ₹10,800 paid in cash, then claimable as ITC.
- TDS under s.195 depends on whether the payment is royalty / FTS / business income under the treaty ⚠️.
- Remittance needs Form 15CA/15CB.

### 8.7 MSME vendor delay

Vendor (Udyam micro, written 45-day terms) bills ₹2,00,000 on 1 Feb. Unpaid on 31 Mar (>45 days
from 1 Feb → due 18 Mar). The ₹2,00,000 is **disallowed** in this year's tax computation and allowed
only when paid. Tax impact at ≈25.17% = ₹50,340 early cash tax, reversed later.

---

## 9. Compliance calendar

| Day | Obligation |
|---|---|
| **7th** | TDS/TCS challan deposit for previous month (30 Apr for March) |
| **11th** | GSTR-1 (monthly filers) |
| **13th** | GSTR-1 for QRMP (quarterly) |
| **15th** | PF / ESI deposit; advance tax on 15 Jun/Sep/Dec/Mar |
| **20th** | GSTR-3B (monthly) — **GST cash due** |
| **22nd/24th** | GSTR-3B QRMP quarterly |
| **25th** | PMT-06 tax payment (QRMP, months 1–2 of quarter) |
| Month-end | Salary, professional tax; reconcile GSTR-2B to purchase register |
| **31 Jul / 31 Oct / 31 Jan / 31 May** | Quarterly TDS statements |
| **30 Sep** | AGM deadline; tax audit |
| **31 Oct** | Company ITR (audit cases) |
| **31 Dec** | GSTR-9 / 9C annual returns 🧠 |
| **30 Nov** | Last day for credit notes against previous FY invoices |

---

## 10. Accounting view

The money-flow design only works if every event posts to the right ledger. Minimum chart of accounts:

| Group | Accounts |
|---|---|
| Assets | Bank (per account), Accounts receivable, **TDS receivable**, **Input CGST / SGST / IGST**, GST cash ledger balance, Advance tax paid, Prepaid, Fixed assets, Security deposits |
| Liabilities | Accounts payable, **Output CGST / SGST / IGST**, **RCM payable**, **TDS payable (by section)**, **TCS payable**, PF/ESI/PT payable, Salary payable, Advance from customers, Provision for tax, Gratuity provision |
| Income | Service revenue (domestic, export), Product sales, Other income, Forex gain |
| Expenses | Salaries, employer PF/ESI, Professional fees, Rent, Software, Travel, Depreciation, **GST on blocked credit**, Bank charges, Interest, Forex loss, Bad debts |
| Equity | Share capital, reserves, retained earnings |

**Rules that bind the data model:**

- Every document holds frozen **tax lines** (component, rate, base, amount), not just totals.
- GST posts per component to a per-registration ledger.
- TDS posts **per section and per PAN** (for threshold and certificate reporting).
- Credit notes and bank-charge write-offs post to their own accounts, never edit history. A bad-debt
  **write-off** is an accounting entry only — it is not a GST credit note (see §7.7).
- Period locks after returns are filed.
- Output formats: Tally / Zoho / generic CSV export, GSTR-1 JSON, TDS statement file.

---

## 11. What this means for FBOS

### 11.1 Services already in the repo that touch finance

| Service | Finance relevance |
|---|---|
| `01_identity` | `LegalEntity`, `TaxRegistration`, org `fiscal_year_start`, `base_currency` — foundation for per-GSTIN everything; **no routes yet** |
| `02_revenue` | Clients, offerings (SAC/GST), quotations, contracts, invoices, payments — sales side; defects D1–D12 listed in the billing plan |
| `03_delivery` | Time tracking, tasks → source of billable hours and milestones |
| `04_control` | Approvals — natural gate for vendor payments, credit notes, write-offs |
| `05_documents` | Invoices PDFs, vendor bills, TDS certificates, 26AS, challans — all as attachments to entities (generic subject-linked attachments) |
| `07_management` | Budgets / KPI targets — profit and cash targets |
| `08_insight` | Audit log, dashboards — tax-liability and free-cash dashboards |
| `09_assets` | **Vendor accounts**, asset tracking — the start of the purchase side |

### 11.2 Gaps this research exposes

The existing billing plan covers **outward supplies + customer TDS**. Not yet modelled:

| Gap | Why it matters |
|---|---|
| **Purchase side** — vendor master, vendor bills, bill approval, payment runs | Source of ITC, TDS-we-deduct, RCM, MSME dues |
| **Vendor tax profile** — PAN, GSTIN, MSME/Udyam, residency, TDS lower-cert, bank | Drives section/rate/threshold and 43B(h) |
| **TDS-payable engine** — section choice, cumulative threshold per PAN, challan, quarterly statement | Penalties for errors are real and automatic |
| **RCM & import-of-service** handling on purchases | Cash goes out before credit comes in |
| **ITC reconciliation** (purchase register ⇄ GSTR-2B) | Credit claimed only if supplier reported |
| **GST ledger / liability computation** per GSTIN per month | Tells finance the cash needed by the 20th |
| **Payroll** (salary, PF, ESI, PT, TDS 392) | Largest outflow; own statutory calendar |
| **Fixed assets & depreciation** (tax vs book) | Links `09_assets` to finance |
| **Advance tax / income-tax estimate** | Needs P&L + TDS receivable + prior payments |
| **Bank accounts & reconciliation** | Money flow is only believable if bank statements tie to the ledgers |
| **Expense claims / reimbursements** | Employees spend company money; GST and TDS implications |
| **Compliance calendar & reminders** | Every date in §9 as a dated task, tied to `06_communication` |
| **Multi-currency / forex** | Export invoices, foreign vendors |

### 11.3 Suggested decomposition (for discussion, not decided)

A new service (say **`10_finance`**) or an expansion of `02_revenue`, owning:

1. **Tax config** (components, rates, rules, sections — dated; shared with billing)
2. **Parties' tax profiles** (customers *and* vendors *and* employees)
3. **Sales documents** (existing billing plan; staged-invoice flow per §7.8)
4. **Purchase documents** (vendor bill, debit note, expense claim)
5. **Payments & bank** (receipts, payment runs, reconciliation)
6. **Ledgers & journal** (general ledger, tax ledgers, period locks)
7. **Returns & compliance** (GST data, TDS statements, calendar)
8. **Payroll** as a separate sub-area (or its own service)

The decision on service boundaries is the user's; the data-model principles in the billing plan §6
(config over code, dated everything, pure engine, snapshot on issue, money as decimal) apply
unchanged to all of it.

---

## 12. Open questions

Answers decide what to build first:

1. **Entity facts:** legal form, **turnover band** (drives e-invoicing, QRMP, tax audit, 115BAA choice), number of GSTINs/states.
2. **Products or services only?** "Service and product" was mentioned; goods bring HSN, stock, e-way bills, customs, and TCS cases.
3. **Export/foreign business?** LUT, FIRC, 15CA/15CB, forex.
4. **Does the company have payroll in-house or outsourced?** Determines whether to model PF/ESI/PT.
5. **Government or PSU customers?** GST-TDS applies.
6. **Is the goal a ledger of record, or an operational layer feeding Tally/Zoho?** Biggest scope driver.
7. **Who files returns** — an external CA via exports, or the product itself (GSP integration)?
8. **Is the product for the user's own company, or multi-tenant for client companies** (the identity service has organizations; billing plan assumes multi-org)? Affects config-per-org and privacy.
9. **Which country packs after India?**

---

## 13. Glossary

| Term | Meaning |
|---|---|
| **AATO** | Aggregate annual turnover, used for e-invoice thresholds |
| **ITC** | Input tax credit — GST paid on purchases, set off against GST collected |
| **RCM** | Reverse charge — buyer pays the GST |
| **LUT** | Letter of undertaking — export without paying IGST |
| **IRN / IRP** | Invoice Reference Number / Invoice Registration Portal (e-invoicing) |
| **GSTR-1 / 3B / 2B** | Outward supplies / summary + payment / auto-generated inward statement |
| **GSP** | GST Suvidha Provider — licensed API intermediary for filing |
| **TDS / TCS** | Tax deducted / collected at source |
| **TAN / PAN** | Deductor's / taxpayer's identifier |
| **26AS / AIS** | Govt statements of tax credited against a PAN |
| **Form 16 / 16A** | TDS certificate for salary / non-salary |
| **DTAA / TRC / 10F** | Tax treaty / residency certificate / info form for foreign payees |
| **15CA / 15CB** | Foreign-remittance declaration / CA certificate |
| **MAT** | Minimum alternate tax on book profit |
| **115BAA** | Concessional 22% corporate regime |
| **43B(h)** | Disallowance for late payment to micro/small vendors (in 2025 Act: 37(2)(g)) |
| **QRMP** | Quarterly return filing, monthly payment (small GST filers) |
| **SAC / HSN** | Service / goods classification code |
| **FIRC** | Foreign inward remittance certificate |
| **Udyam** | MSME registration |
| **Receipt voucher** | GST document for advances on services |

---

## 14. Sources

All secondary (commentary / vendor sites). Use only to orient; confirm with the Act, CBIC, CBDT, EPFO/ESIC and
state notifications.

**GST**
- [Cleartax — GST rates](https://cleartax.in/s/gst-rates)
- [WION — GST 2.0 two slabs 5% and 18%, 40% for sin goods](https://www.wionews.com/india-news/gst-meeting-council-gives-nod-to-two-tier-tax-structure-common-people-farmers-to-be-benefited-says-sitharaman-1756917961983/amp)
- [Moneylife — GST 2.0 FAQs](https://moneylife.in/article/gst-20-faqs/78175.html)
- [Taxaj — RCM list 2026](https://www.taxaj.com/learn/?p=710)
- [Taxguru — reverse charge services](https://taxguru.in/goods-and-service-tax/reverse-charge-services-gst.html)
- [Incorpx — ITC rules 2026](https://www.incorpx.io/blog/gst-input-tax-credit-rules-claiming-itc-2026)
- [CBIC — CGST Act s.13 time of supply of services](https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter4/section13_v1.00.html)
- [Taxguru — credit/debit notes, s.34](https://taxguru.in/goods-and-service-tax/debit-note-credit-note-section-34-cgst-act-2017.html)
- [Taxguru — when buyer must pay supplier (180-day ITC reversal)](https://taxguru.in/goods-and-service-tax/when-buyer-pay-gst-registered-supplier.html)
- [Taxaj — GST return due dates 2026](https://www.taxaj.com/learn/?p=392)
- [Calcguru — GST late fee and interest](https://calcguru.in/?p=572)

**TDS / TCS / Income-tax Act 2025**
- [India Briefing — Section 393 FAQs](https://www.india-briefing.com/news/section-393-income-tax-act-2025-tds-rules-rates-compliance-guide-44450.html/)
- [OneFinOps — Section 393 TDS tables](https://onefinops.com/blog/section-393-income-tax-act)
- [Karnanica — new TDS challan codes FY 2026-27](https://www.karnanica.com/new-tds-challan-codes-fy-2026-27/)
- [Taxguru — TDS rates and thresholds TY 2026-27](https://taxguru.in/income-tax/income-tax-act-2025-tds-rates-thresholds-compliance-ty-2026-27.html)
- [Cleartax — TDS and TCS changes from April 2026](https://cleartax.in/s/tds-and-tcs-changes-from-april-2026)
- [India Briefing — TDS rates FY 2025-26](https://india-briefing.com/news/a-guide-to-indias-tds-rates-for-fy-2025-26-36999.html)
- [KoinX — TDS due dates FY 2026-27](https://www.koinx.com/tax-guides/tds-return-filing-payment-due-dates)
- [Teachoo — TDS late-deposit interest](https://www.teachoo.com/subjects/tax-practical/practical-tds-(non-salary)/tds-interest-and-penalty-calculation/)

**Corporate tax**
- [Motilal Oswal — corporate tax in India](https://www.motilaloswal.com/personal-finance/tax/corporate-tax-in-india-2025-26-rates-regimes-complete-guide)
- [5paisa — Section 115BAA](https://5paisa.com/stock-market-guide/tax/section-115baa)
- [Income Tax Dept — Section 211 (advance tax)](https://www.incometaxindia.gov.in/w/section-211)
- [Taxguru — Section 43B(h) MSME payments](https://www.taxguru.in/income-tax/section-43bh-msme-payment.html)
- [Taxguru — Finance Ministry clarification on 43B(h)](https://taxguru.in/income-tax/finance-ministry-clarifies-section-43bh-45-day-msme-payment-rule.html)

**Payroll**
- [SCC Online — Ministry FAQs on four labour codes](https://www.scconline.com/blog/post/2026/04/26/ministry-faqs-four-labour-codes-india-2026/)
- [Kredily — new wage code payroll impact](https://kredily.com/new-wage-code-india-2026-payroll-impact/)
- [HROne — professional tax slabs 2026-27](https://hrone.cloud/blog/professional-tax-slab-rates-2026-27/)

**Internal**
- [`tax-and-billing-plan.md`](tax-and-billing-plan.md) — the sales-side design this document extends.

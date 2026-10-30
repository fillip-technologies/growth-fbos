# People: roles, multiple posts and identity sync — plan

Status: **plan, not built.** Written 2026-10-30.

What exists today (built and merged): employee ID numbers and bank accounts, the onboarding
checklist, salary breakdown, and promotions / demotions / transfers with a second approver
(`role_changes`, permission `people.role_change.approve`).

This plan covers what comes next:

1. Keeping People and Identity in sync (what "role" means in each).
2. One person holding several posts in the company.
3. Doing both the way large HR systems do.

---

## 1. Two kinds of "role"

| | Identity "Roles" (sidebar) | People "role" |
|---|---|---|
| What it is | A named bundle of **permissions** (`admin`, `member`, custom), applied to a user, optionally limited to a department | The **job**: designation, department, manager, position seat |
| Controls | What the person can do in the app | What the person's job is |
| Lives in | `roles`, `role_assignments` (identity) | `workers`, `position_assignments`, `role_changes` (people) |

Today nothing connects them: a promotion changes the title but not access, and a department or
manager changed in one service is not changed in the other.

## 2. Who owns what

People owns the HR facts; Identity owns login and access (the usual HR-system → identity-system split).

| Data | Owner | Flow |
|---|---|---|
| Designation, level, seat, joining / exit dates | People | stays in People |
| Department, manager, employee code, name, phone — for anyone with an employee record | People | People → Identity |
| Email (login ID), password, MFA, sessions | Identity | stays in Identity |
| Access roles and permissions | Identity | driven by People's role change (section 4) |
| Login active / deactivated | Identity | People → Identity when an exit takes effect |

- Users with no employee record (client admins, service accounts) stay entirely in Identity.
- In the Identity Users page, a linked person's department, manager, employee code, name and phone
  become read-only: "Managed in People", with a link. Nobody edits one fact in two places.

## 3. How the large systems do it

Sources: university Workday job aids and SAP knowledge-base articles (not Workday's own docs), and
vendor blogs for the identity part. Treat product detail with some caution. Nothing found on
birthright (default) access; that part is general practice.

**Workday — additional jobs with approval**
- A worker has one primary job and any number of additional jobs.
- "Add Additional Job" starts from the worker profile. The user picks the supervisory organization,
  an effective date and a reason. The position list shows only **vacant positions** open on that date.
- It routes through an HR partner, **both department heads**, then budget and payroll. The employee
  **cannot start the extra job until approval completes**.
- <https://employees.tamu.edu/compensation/job-changes/add-job.html>
- <https://it.tamus.edu/workdayservices/training/job_aid/add-additional-job/>
- <https://doc.workday.com/admin-guide/en-us/human-capital-management/staffing/job-overlap/dan1370797464534.html>

**SAP SuccessFactors — one person, several employments**
- A **person ID** never changes; each employment has its own user ID. A switcher moves between employments.
- <https://userapps.support.sap.com/sap/support/knowledge/en/2436222>
- <https://userapps.support.sap.com/sap/support/knowledge/en/2495643>
- <https://blogs.sap.com/2019/12/23/managing-employments-across-the-successfactors-suite/>

**HR drives identity (joiner / mover / leaver)**
- The HR system is the source of truth; the identity system provisions accounts and access, often over SCIM.
- A **mover** event adds new access, **removes stale access** and updates approver chains. Access is
  often assigned by rules on department, title and location.
- <https://docs.veza.com/4yItIzMvkpAvMVFAamTf/features/lifecycle-management/lcm-workday-okta-ad>
- <https://www.okta.com/video/oktane18-Modernize-IT-%20Bringing-HR-and-Directories-Together>
- <https://startwithidentity.com/guides/implementation/user-lifecycle-management-guide/>

## 4. Job role maps to access role

- A settings table in People maps a **job profile** (falling back to **designation**) to one or more
  Identity access roles, with an optional department scope.
  Example: "Sales Manager" → the Sales Manager role for their department.
- The role-change approval screen shows the access impact ("+ Sales Manager, − Sales Executive"), so the
  approver signs off on title, pay and access together.
- On apply, People asks Identity to add the mapped roles and remove the ones People previously granted.
  Assignments People creates are **tagged**; roles granted by hand in Identity are never touched.
- Only mapped roles can be granted this way. Mapping to a high-privilege role (such as admin) needs
  the identity role-assignment permission.
- Separation-of-duties checks: a conflicting pair of roles is refused.

## 5. Several posts for one person

### What a post is

A **post** is one job a person holds: a title in a department, a manager, a share of their time and
dates. A person always has exactly one active **primary** post and may have more.

| Post type | Example | Share of time |
|---|---|---|
| Primary | Sales Manager, Sales dept | e.g. 60% |
| Concurrent | Part-time Trainer, HR dept | e.g. 40% |
| Additional charge | Branch Head, Pune, on top of the main job | none; usually an allowance |
| Acting | Acting Head of Finance while the head is on leave | none; has an end date |

### Model

- One person = one employee record = **one login** (the Workday model). SAP's separate employment per
  contract is only needed for legally separate employments (different legal entities); not planned.
- New **effective-dated `worker_posts`** table: type, title, department, optional position seat,
  reporting manager, time share, optional monthly allowance, start / end dates, status
  (scheduled, active, ended), and the role change that created it. A change ends the old version and
  adds a new one, so "what was their title and manager on 1 March?" has an answer.
- The employee's current designation, department and manager become a **copy of the primary post**, so
  lists and filters keep working.
- Migration creates a primary post for every current employee from their current fields and links
  their current seat where one exists.
- Rules:
  - exactly one active primary post;
  - primary + concurrent time shares add up to 100% or less; additional-charge and acting posts carry none;
  - the last post cannot be ended (that is an exit);
  - a maximum number of posts per person (company setting, default 3);
  - no duplicate post with the same title and department.
- A post can exist without a formal position seat (acting roles often have none).

### Seats and budget

- Seats are budgeted. Only **vacant** seats can be picked; over-budget needs an extra approval.
- A seat can hold more than one person (job sharing) while time shares add up to the seat's budgeted FTE.
  A seat shows "filled" only when its FTE is fully used (today it is all-or-nothing).

### Role changes work per post

The Change role form first asks **which post**:
- **Change** an existing post: promote, demote or transfer that post (its manager and seat apply to it).
- **Add** a post: type, start date, optional end date, time share, allowance.
- **End** a post: with an end date.
- **Make primary**: swap primary and secondary.

The new post does not start until approved (as in Workday).

### Manager, leave and approvals

- Leave, attendance and expense approvals go to the **primary post's manager** by default.
- The org chart shows the primary manager as a solid line and each additional post's manager as a dotted line.

### Pay

- One salary package per person. Each active additional-charge or acting post can add an allowance line
  to the payslip while the post is active.

### Identity effects

- A user's access roles are the **union** of the roles mapped from all active posts, each scoped to that
  post's department. Ending a post removes only the roles that post granted.
- The primary post's department becomes the Identity user's home department; its manager the Identity manager.
- Identity allows extra team memberships only for teams. Posts in other departments are mapped to
  department-scoped roles; team memberships are added only where the post is in a team.

## 6. Approvals as a business process

Today a role change has one second approver. The professional version is a configurable process:

- Routing depends on the change:
  - pay change → add finance;
  - new additional post → **both** department heads;
  - demotion → add the HR head;
  - going over budgeted headcount → add finance.
- Approvers can **delegate** while away; a stalled request **escalates** after a set number of days.
- The platform already has an approvals module (Control: approval policies, steps, delegations, SLAs).
  The plan is to submit role changes as Control approval requests with a `people.role_change` policy
  instead of building a second engine. **To verify before committing:** that Control's API supports
  conditional routing and an external subject. If not, extend People's own approval with steps.
- Requester ≠ approver stays enforced.

## 7. Identity lifecycle (joiner / mover / leaver)

- **Joiner:** create or link the login; give default access for the primary post.
- **Mover:** apply new access, **remove access the old post granted**, update department and manager.
- **Leaver:** deactivate the login on the **last working day** (scheduled by the worker).
  The finalize-exit screen already says it does this; the code currently only records an event.
- Delivery: through the People outbox, with a relay that retries until Identity confirms, so a failure
  never loses a change or breaks a screen. A new token-protected, repeat-safe internal Identity endpoint
  updates placement and manages tagged role assignments.
- People publishes events ("employee moved", "post ended") for other services: Delivery updates team
  membership, Assets creates handover tasks, Communication sends notices.
- A nightly **drift check** compares both sides (department, manager, status) and shows "In sync" or
  what differs on the profile. It reports; it does not fix silently.

## 8. Screens

- Identity Users page: an "Employee record" panel (designation, status, link to the People profile).
- People profile: an "Access" section (Identity roles, read-only, link to manage); a **Posts** tab
  (type, title, department, manager, share, dates, status; Add / End / Change / Make primary);
  sync status.
- Employee lists show the primary title and "+1 more".
- Change role form: which post; approval preview with the route and the access impact.
- Org chart with dotted lines.

## 9. Audit and controls

- Every change keeps who requested, who approved, when and why (timeline + role change history).
- Access granted by a job is **recertified** periodically by the manager, sensitive roles first.
- Pay stays hidden by field permission (already in place).

## 10. Build order

| Phase | Work |
|---|---|
| 1 | Effective-dated posts table, migration (primary post per employee), rules, API |
| 2 | Role changes per post (change, add, end, make primary) with vacancy and FTE checks |
| 3 | Approvals through Control: `people.role_change` policy, conditional routing, delegation, escalation (after verifying Control's API) |
| 4 | Lifecycle sync to Identity: placement, mapped roles, leaver deactivation, outbox relay, drift check |
| 5 | Screens: Posts tab, updated Change role form with approval preview and access impact, dotted-line org chart, "Managed in People" on Identity |
| 6 | Controls: access recertification, separation-of-duties checks, reports by post and FTE, seat sharing by FTE, post allowances on payslips |

## 11. Decisions needed

1. One person with one login and several jobs (recommended), or separate legal employments?
2. Approvals through the Control module with conditional routing (recommended, after checking its API)?
3. Standing approvers for extra posts: HR head, finance, both department heads?
4. Deactivate leavers' logins on the last working day (recommended) or when the exit is finalized?
5. Access recertification now or later?
6. Time shares (60% / 40%) or only a primary post with additional duties?
7. Allowances for extra posts paid through payroll, or only recorded?
8. Which manager approves leave and expenses: primary post's manager (recommended) or any?
9. Maximum posts per person (suggested 3).
10. May one seat be shared by two people?
11. Are posts without a formal position seat allowed (recommended yes)?
12. Mapping by job profile with a designation fallback (recommended), or designation only?
13. Does the approver of an access change need the identity role-assignment permission, or is the
    role-change approval enough? (Recommended: the permission is required to *create the mapping*.)

**Defaults if no answers are given:** one login with several jobs, approvals through Control,
last-working-day deactivation, time shares, allowances through payroll, primary manager approves,
max 3 posts, seat sharing by FTE, seatless posts allowed, mapping by job profile with designation fallback,
recertification later.

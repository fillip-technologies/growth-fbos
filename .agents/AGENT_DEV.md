# Better Code Writing — Agent Guidelines

## Purpose

Use these guidelines whenever you write, modify, refactor, or review code.

The goal is not to make code more sophisticated. The goal is to make code:

- Easy to understand
- Easy to change
- Easy to test
- Harder to break
- Easy for another developer or coding agent to reason about
- Resilient to future changes

The core principle behind all rules in this document is:

> **Make the next change easier.**

Do not optimize only for "does this code work right now?".
Also consider:

- Can someone understand it quickly?
- Can someone safely modify it later?
- Can the behavior be tested independently?
- Are external dependencies isolated?
- Can invalid states be prevented?
- Are failures understandable?
- Is the change focused enough to review?

---

# 1. Keep the Main Path Easy to Follow

## Rule

Keep the important execution path of a function visible.

Avoid deeply nested conditional structures when early returns can make the logic clearer.

### Prefer

```ts
function processOrder(user: User, order: Order) {
  if (!user) {
    return { error: "USER_NOT_FOUND" };
  }

  if (!user.isActive) {
    return { error: "USER_INACTIVE" };
  }

  if (!user.canPurchase) {
    return { error: "PERMISSION_DENIED" };
  }

  return createOrder(order);
}
````

### Avoid

```ts
function processOrder(user: User, order: Order) {
  if (user) {
    if (user.isActive) {
      if (user.canPurchase) {
        return createOrder(order);
      } else {
        return { error: "PERMISSION_DENIED" };
      }
    } else {
      return { error: "USER_INACTIVE" };
    }
  }

  return { error: "USER_NOT_FOUND" };
}
```

The second version may work, but the main operation is buried inside nested conditions.

## Guidelines

* Validate preconditions early.
* Return early when a required condition fails.
* Keep the successful/main path visually obvious.
* Avoid unnecessary nesting.
* Do not blindly remove all nesting.
* Use nesting when it genuinely improves the logical structure.

## Agent Checklist

Before finishing a function, ask:

* Can I understand the main operation by scanning the function?
* Are failure conditions handled early?
* Is important business logic buried inside multiple `if` statements?
* Would an early return make the code easier to understand?

---

# 2. Name Things by Meaning

## Rule

Names should communicate what something represents and why it exists.

Avoid vague names such as:

```ts
data
result
item
value
obj
info
response
temp
thing
processData()
handleData()
doStuff()
```

These names force the reader to inspect surrounding code to understand the meaning.

### Avoid

```ts
const data = await getOrder();

const result = process(data);

return result;
```

### Prefer

```ts
const pendingOrder = await getPendingOrder();

const processedOrder = processOrder(pendingOrder);

return processedOrder;
```

The second version communicates intent immediately.

## Good Naming Principles

Name variables based on:

* Business meaning
* Domain meaning
* Actual responsibility
* State
* Expected behavior

For example:

```ts
pendingOrder
paidOrder
customer
verifiedUser
checkoutSession
paymentAttempt
failedPayment
availableProducts
```

are generally more useful than:

```ts
data
item
userData
response
result
list
```

## Function Names

Function names should describe the action or intention.

### Weak

```ts
handle()
process()
run()
execute()
doSomething()
```

### Better

```ts
processPayment()
validateCheckout()
calculateOrderTotal()
sendOrderConfirmation()
createPaymentIntent()
```

## Do Not Overdo Naming

Good names do not need to be unnecessarily long.

Avoid:

```ts
theCurrentlyAuthenticatedUserWhoIsTryingToPlaceAnOrder
```

Prefer:

```ts
currentUser
```

The goal is **clarity**, not maximum word count.

## Agent Checklist

Ask:

* Does this name communicate meaning?
* Does the reader need to inspect another function to understand the variable?
* Is the name specific enough for the domain?
* Does the function name describe what it actually does?
* Can a better name remove the need for a comment?

---

# 3. Keep External Systems Behind a Boundary

## Rule

External services should not leak their internal structure throughout your application.

External systems include:

* Payment providers
* Email providers
* Authentication providers
* Cloud services
* Third-party APIs
* External databases
* SaaS APIs
* SDKs

Your application should translate external data into your own application's domain model at the
boundary.

---

## Problem

Imagine an external payment provider returns:

```json
{
  "cust_id": "123",
  "cust_fname": "John",
  "cust_email_addr": "john@example.com"
}
```

Do not spread these external names throughout the application:

```ts
if (customer.cust_id) {
  sendEmail(customer.cust_email_addr);
}
```

Now your entire application depends on the external API's naming.

If the provider changes:

```text
cust_id
```

to:

```text
customer_id
```

the change can spread across the codebase.

---

## Prefer an Adapter / Boundary

```ts
type Customer = {
  id: string;
  firstName: string;
  email: string;
};

function mapExternalCustomer(response: ExternalCustomer): Customer {
  return {
    id: response.cust_id,
    firstName: response.cust_fname,
    email: response.cust_email_addr,
  };
}
```

The rest of the application uses:

```ts
customer.id
customer.firstName
customer.email
```

The external API's structure stays at the boundary.

---

## Boundary Principle

Think of external systems like this:

```text
External API
     |
     v
[ Adapter / Mapper ]
     |
     v
Application Domain
     |
     v
Business Logic
```

Do not allow:

```text
External API
     |
     +-----> Business Logic
     |
     +-----> Database
     |
     +-----> Controllers
     |
     +-----> UI
```

with external API-specific fields everywhere.

## Agent Rules

When integrating an external system:

1. Identify external-specific types.
2. Keep them close to the integration layer.
3. Convert external data into application/domain types.
4. Keep business logic independent from provider-specific field names.
5. Keep provider-specific error handling at the boundary where practical.
6. Avoid importing external SDK types throughout unrelated business logic unless there is a strong
   reason.

## Important

Do not introduce unnecessary abstraction layers just for the sake of abstraction.

Use a boundary when it provides meaningful isolation from an external dependency.

---

# 4. Make Invalid States Harder to Represent

## Rule

Use types and data structures to represent valid states accurately.

Avoid making everything optional when the application knows that certain values must exist.

---

## Weak Model

```ts
type Order = {
  id?: string;
  paymentId?: string;
  status?: "pending" | "paid" | "failed";
};
```

Now every consumer must ask:

```ts
if (order.id) {
  if (order.paymentId) {
    if (order.status === "paid") {
      // ...
    }
  }
}
```

The type does not communicate the actual state.

---

## Better Model

Represent the state explicitly.

```ts
type PaidOrder = {
  id: string;
  paymentId: string;
  status: "paid";
};
```

Now:

```ts
function sendReceipt(order: PaidOrder) {
  sendReceiptEmail(order.id, order.paymentId);
}
```

The function does not need to repeatedly check whether the payment ID exists.

---

## State-Specific Types

When useful, model states separately:

```ts
type PendingOrder = {
  id: string;
  status: "pending";
};

type PaidOrder = {
  id: string;
  paymentId: string;
  status: "paid";
};

type FailedOrder = {
  id: string;
  status: "failed";
  failureReason: string;
};
```

This can make illegal combinations difficult or impossible to represent.

---

## General Principle

Prefer:

```text
Valid state -> Explicit type
```

over:

```text
Everything optional -> Check validity everywhere
```

## Agent Rules

When designing or modifying types:

* Do not make fields optional without a reason.
* Ask whether the field is actually optional.
* Represent lifecycle states when they have different requirements.
* Use discriminated unions where appropriate.
* Use domain-specific types when they prevent invalid combinations.
* Push validation toward boundaries.
* Do not rely entirely on runtime checks when the type system can express the invariant.

## Important

Do not create dozens of types for trivial cases.

Use stronger modeling when:

* States have different required fields.
* Operations are only valid in certain states.
* Invalid combinations could cause bugs.
* The domain has meaningful state transitions.

---

# 5. Separate Decisions From Actions

## Rule

Separate business decisions from side effects.

A business decision answers:

> "Should this happen?"

An action/side effect performs:

> "Make it happen."

Do not unnecessarily combine both.

---

## Example of Mixed Responsibilities

```ts
async function processUser(userId: string) {
  const user = await database.getUser(userId);

  if (user.isVerified && user.age >= 18) {
    await database.enableFeature(userId);
    await email.sendWelcomeEmail(user.email);
  }
}
```

The business rule is mixed with:

* Database access
* Database mutation
* Email sending

That makes the rule harder to test independently.

---

## Prefer

```ts
function isEligibleForFeature(user: User): boolean {
  return user.isVerified && user.age >= 18;
}
```

Then:

```ts
async function processUser(userId: string) {
  const user = await database.getUser(userId);

  if (!isEligibleForFeature(user)) {
    return;
  }

  await database.enableFeature(userId);
  await email.sendWelcomeEmail(user.email);
}
```

Now the decision can be tested independently.

---

## Useful Areas

This pattern is especially useful for:

* Permissions
* Authorization
* Validation
* Pricing
* Discounts
* Retry decisions
* Notifications
* Eligibility
* Feature flags
* Workflow transitions
* Business rules

---

## Example: Retry Decision

Instead of:

```ts
async function handleFailure(error: Error) {
  if (error.status === 500 || error.status === 503) {
    await queue.retry();
  }
}
```

Consider:

```ts
function shouldRetry(error: ApiError): boolean {
  return error.status === 500 || error.status === 503;
}
```

Then:

```ts
if (shouldRetry(error)) {
  await queue.retry();
}
```

The decision is independently testable.

---

## Agent Checklist

Ask:

* Is business logic mixed with database calls?
* Is business logic mixed with network calls?
* Is business logic mixed with email/notifications?
* Can the important decision be extracted into a pure function?
* Can I test the decision without mocking several external systems?

Do not extract every `if` statement into a function.

Extract decisions when they represent meaningful business logic.

---

# 6. Make Errors Useful

## Rule

Errors should provide enough information for both humans and systems to understand and handle
failures.

Avoid generic errors such as:

```text
Something went wrong.
```

They provide very little actionable information.

---

## Use Predictable Error Codes

Instead of relying only on text:

```ts
throw new Error("Something went wrong");
```

Prefer a structured error:

```ts
throw new AppError({
  code: "PAYMENT_DECLINED",
  message: "The payment provider declined the payment",
});
```

The exact implementation can vary.

For example:

```ts
type ErrorCode =
  | "USER_NOT_FOUND"
  | "PERMISSION_DENIED"
  | "PAYMENT_DECLINED"
  | "ORDER_NOT_FOUND";
```

Now systems can reliably handle errors:

```ts
if (error.code === "PAYMENT_DECLINED") {
  showPaymentFailureMessage();
}
```

rather than parsing human-readable text.

---

## Human vs System Information

Think of errors as having two audiences:

### Humans

Need:

* Useful message
* Context
* What operation failed
* Where to investigate

### Systems

Need:

* Stable error code
* Predictable structure
* Machine-readable fields
* Consistent behavior

Therefore:

```text
Message -> Humans
Code    -> Systems
Context -> Developers
```

---

## Logging

Logs should contain useful debugging context.

Useful:

```ts
logger.error("Failed to process payment", {
  orderId,
  paymentProvider,
  errorCode: error.code,
});
```

Avoid useless logs:

```ts
logger.error("Something went wrong");
```

---

## Never Log Secrets

Never log:

* Passwords
* Authentication tokens
* API keys
* Session secrets
* Credit card data
* Private credentials
* Sensitive personal information

Bad:

```ts
logger.error("Payment failed", {
  token,
  password,
  creditCardNumber,
});
```

Good:

```ts
logger.error("Payment failed", {
  orderId,
  paymentId,
  errorCode,
});
```

Only log information that is necessary and safe.

---

# 7. Keep Changes Focused

## Rule

Keep each code change focused on a clear purpose.

Avoid large changes that mix unrelated work.

---

## Avoid

One pull request that:

* Adds a checkout feature
* Refactors the payment service
* Changes database schema
* Rewrites frontend components
* Changes retry behavior
* Renames unrelated APIs
* Reformats the entire repository

Even if the final result works, the change is difficult to:

* Review
* Test
* Debug
* Understand
* Revert
* Merge safely

---

## Prefer Focused Changes

For example:

```text
Change 1:
Add checkout validation.

Change 2:
Refactor payment service.

Change 3:
Update checkout UI.

Change 4:
Modify retry handling.
```

Each change has a clear purpose.

---

## Agent Rules

When implementing a request:

1. Identify the requested behavior.
2. Change only the code necessary for that behavior.
3. Avoid unrelated refactoring.
4. Avoid unnecessary renaming.
5. Avoid formatting unrelated files.
6. Avoid changing architecture unless required.
7. Keep the diff understandable.
8. If a refactor is necessary, keep it closely related to the requested change.

---

# 8. Core Engineering Principle

All seven practices support one larger principle:

> **Make the next change easier.**

Good code is not merely code that works today.

Good code allows future developers and agents to:

* Understand it quickly
* Modify it safely
* Test it independently
* Diagnose failures
* Change external integrations
* Reason about valid states
* Review changes confidently

Think beyond the current implementation.

Ask:

> "What will happen when someone needs to change this six months from now?"

---

# 9. Agent Code-Writing Workflow

Use this workflow when implementing a feature or fixing a bug.

## Step 1 — Understand the Existing Code

Before changing code:

* Find the relevant entry point.
* Understand the existing flow.
* Identify business rules.
* Identify external dependencies.
* Identify data models.
* Check existing tests.
* Check existing conventions.

Do not immediately rewrite code.

---

## Step 2 — Identify the Main Path

Determine:

```text
Input
  ↓
Validation
  ↓
Business Decision
  ↓
Action / Side Effect
  ↓
Output
```

Keep this flow understandable.

---

## Step 3 — Check Naming

Before adding new variables/functions/types:

Ask:

* Does the name communicate intent?
* Is it domain-specific?
* Is it unnecessarily generic?
* Does it match existing project terminology?

---

## Step 4 — Check Boundaries

Ask:

* Am I dealing with an external API?
* Am I leaking external types into domain logic?
* Should this response be mapped?
* Should provider-specific behavior stay inside an adapter?

---

## Step 5 — Check State Modeling

Ask:

* Can this value actually be missing?
* Are multiple states represented?
* Do different states require different fields?
* Can the type system prevent invalid combinations?

---

## Step 6 — Separate Decisions and Actions

Identify:

```text
Decision:
Should this happen?

Action:
Perform it.
```

When appropriate, keep those responsibilities separate.

---

## Step 7 — Design Useful Errors

For every important failure:

* Provide a stable error code.
* Provide a useful human-readable message.
* Include safe debugging context.
* Never expose secrets.

---

## Step 8 — Keep the Diff Focused

Before finishing:

* Remove unrelated changes.
* Remove unnecessary refactors.
* Remove accidental formatting changes.
* Remove unused code.
* Keep the change tied to the requested goal.

---

# 10. Code Review Checklist

Before considering a change complete, review it against this checklist.

## Readability

* [ ] Is the main execution path easy to follow?
* [ ] Is unnecessary nesting avoided?
* [ ] Are important conditions visible?
* [ ] Are functions reasonably focused?

## Naming

* [ ] Do variables have meaningful names?
* [ ] Do functions describe their behavior?
* [ ] Are generic names avoided?
* [ ] Does terminology match the domain?

## External Dependencies

* [ ] Are third-party APIs isolated?
* [ ] Are external response formats mapped where appropriate?
* [ ] Is provider-specific logic contained?
* [ ] Is external complexity prevented from spreading?

## Types and State

* [ ] Are unnecessary optional fields avoided?
* [ ] Are important states represented explicitly?
* [ ] Can invalid combinations be prevented?
* [ ] Are invariants expressed in types where practical?

## Business Logic

* [ ] Are important decisions easy to test?
* [ ] Are side effects separated when appropriate?
* [ ] Is business logic mixed unnecessarily with infrastructure?

## Errors

* [ ] Are errors meaningful?
* [ ] Do important errors have stable codes?
* [ ] Is enough context logged?
* [ ] Are secrets and sensitive data excluded from logs?

## Scope

* [ ] Is the change focused?
* [ ] Are unrelated files untouched?
* [ ] Is unrelated refactoring avoided?
* [ ] Is the diff easy to review?
* [ ] Can the change be safely reverted?

---

# 11. Before/After Mental Model

When writing code, prefer this:

```text
Readable
    ↓
Understandable
    ↓
Testable
    ↓
Changeable
    ↓
Maintainable
```

Avoid optimizing only for:

```text
Short
    ↓
Works
```

Shorter code is not automatically better code.

The best code communicates its intent clearly.

---

# 12. Practical Rules for the Coding Agent

Follow these rules by default:

### Rule 1

Prefer early returns when they make the main path easier to see.

### Rule 2

Use names that communicate domain meaning.

### Rule 3

Keep third-party API details at integration boundaries.

### Rule 4

Use types to represent valid states accurately.

### Rule 5

Make meaningful business decisions independently testable when practical.

### Rule 6

Separate business decisions from side effects when doing so improves clarity or testability.

### Rule 7

Use structured, predictable errors.

### Rule 8

Provide useful debugging context without logging secrets.

### Rule 9

Keep implementation changes focused on the requested goal.

### Rule 10

Do not perform unrelated refactoring just because you noticed an opportunity.

### Rule 11

Do not add abstractions unless they solve a real problem.

### Rule 12

Prefer simple code that communicates intent over clever code.

### Rule 13

Optimize for the next developer or agent who will modify the code.

### Rule 14

When two implementations are functionally equivalent, generally prefer the one that is easier to
understand and change.

---

# 13. Final Decision Framework

When choosing between two valid implementations, evaluate them in this order:

1. **Correctness**

    * Does it produce the required behavior?

2. **Clarity**

    * Can another developer understand it quickly?

3. **Changeability**

    * Can the implementation be modified without touching many unrelated areas?

4. **Testability**

    * Can important behavior be tested without excessive setup or mocking?

5. **Safety**

    * Does the design prevent invalid states and reduce accidental misuse?

6. **Isolation**

    * Are external dependencies contained?

7. **Error Handling**

    * Are failures understandable and machine-readable?

8. **Scope**

    * Does the implementation avoid unnecessary changes?

Do not sacrifice correctness for simplicity.

Do not sacrifice maintainability for cleverness.

Do not add complexity without a clear benefit.

---

# 14. Golden Rule

Whenever you write or modify code, ask:

> **"Am I making the next change easier or harder?"**

If the change makes future work easier while preserving correctness, it is generally moving in the
right direction.

The objective is not to write more code.

The objective is to write code that people and agents can:

* Understand
* Change
* Test
* Debug
* Review
* Trust

**Make the next change easier.**


#!/usr/bin/env python3
"""
fuzz_enforcement.py -- adversarial property tests for the Khaao enforcement surface.

WHY THIS EXISTS
  simulate.py proves the 10 attack shapes you *wrote*. A naive-obedient mock
  only does what a message asks, so it never wanders into inputs you didn't
  script. This throws random / hostile / malformed values straight at the
  enforcement functions and checks a small set of INVARIANTS that must hold
  no matter what sequence of calls happens.

HOW TO USE IT AGAINST YOUR REAL CODE
  Delete ReferenceEnforcement (and the `E = ReferenceEnforcement()` lines) and
  import your module instead:
      from enforcement import issue_refund, get_order, log_event
  Point the PROPERTIES at your functions. Everything else stays.
  Stdlib only -- runs in Termux with `python3 fuzz_enforcement.py`. No pip.

THE INVARIANTS
  I2  total PAID refunds never exceed the weekly pool (Rs 15,000)
  I3  a refund is only ever PAID for a real, positive, finite amount <= cap;
      negative / zero / NaN / inf / oversized must escalate or reject, never pay
  I4  every rupee paid maps to a known order id (no orphan payouts)
  I5  a food-safety refund is never blocked by the pool that abuse drains
  I6  a duplicate provider message id causes at most one state change
  I7  a support requester never receives customer PII (redaction is server-side)

  The reference mock below is SPEC-COMPLETE: it passes all 10 simulate.py
  tests. It still fails I3, I5, I6 -- which is the point. Those holes live
  outside the shapes you scripted. I7 passes, to show the harness isn't
  rigged all-red.
"""

import math
import random

AUTO_CAP = 500          # Rs -- per-refund auto-approve ceiling
WEEKLY_POOL = 15_000    # Rs -- total auto-refunds per week
VELOCITY_N = 2          # refunds per customer / 30d before escalation
PII_KEYS = {"phone", "customer_phone", "address", "customer_address"}


class Result:
    def __init__(self, action, amount=0.0, reason=""):
        self.action = action          # "paid" | "escalated" | "rejected"
        self.amount = amount
        self.reason = reason

    def __repr__(self):
        return f"Result({self.action}, {self.amount!r}, {self.reason!r})"


class ReferenceEnforcement:
    """Spec-complete per the README's 10 tests. Deliberately does NOT guard
    things the spec never named -- non-finite / negative amounts, a food-safety
    carve-out, message-id dedup -- so the fuzzer can demonstrate those gaps."""

    def __init__(self):
        self.orders = {}
        self.refunded_orders = set()
        self.paid = []            # (order_id, amount)
        self.weekly_paid = 0.0
        self.cust_refunds = {}
        self.log = []             # (event, message_id)

    def add_order(self, oid, customer, total, restaurant="r1",
                  phone="0300-0000000", active=True):
        self.orders[oid] = dict(customer=customer, total=total,
                                 restaurant=restaurant, phone=phone, active=active)

    def issue_refund(self, order_id, amount, reason="", message_id=None):
        if order_id not in self.orders:
            return Result("rejected", reason="unknown order")
        if order_id in self.refunded_orders:                 # one-per-order (#3)
            return Result("rejected", reason="already refunded")
        cust = self.orders[order_id]["customer"]
        if self.cust_refunds.get(cust, 0) >= VELOCITY_N:     # velocity (#8)
            return Result("escalated", amount, "velocity")
        if amount > AUTO_CAP:                                # over cap (#4)
            return Result("escalated", amount, "over cap")
        if self.weekly_paid + amount > WEEKLY_POOL:          # pool hard-stop (#9)
            return Result("rejected", reason="weekly pool exhausted")
        # PAY -- note: no check that amount is positive/finite, no safety carve-out
        self.refunded_orders.add(order_id)
        self.paid.append((order_id, amount))
        self.weekly_paid += amount
        self.cust_refunds[cust] = self.cust_refunds.get(cust, 0) + 1
        return Result("paid", amount, reason)

    def get_order(self, order_id, requester):
        o = self.orders.get(order_id)
        if not o:
            return None
        view = {"order_id": order_id, "total": o["total"]}   # PII stripped server-side
        if requester == "restaurant:" + o["restaurant"] and o["active"]:
            view["customer_phone"] = o["phone"]
        return view

    def log_event(self, event, message_id=None):
        self.log.append((event, message_id))                 # no dedup
        return len(self.log)


# ---------------------------------------------------------------------------
# adversarial input generators
# ---------------------------------------------------------------------------
def adversarial_amount():
    return random.choice([
        random.uniform(1, 1000),      # normal
        random.uniform(-1000, -1),    # negative -> a *charge* disguised as refund
        0.0,                          # zero
        float("nan"),                 # poisons every later comparison
        float("inf"), float("-inf"),
        1e18,                         # absurd
        AUTO_CAP + 1,                 # just over cap -> must escalate
        0.0001,                       # sub-rupee dust
    ])


# ---------------------------------------------------------------------------
# properties -- each returns (ok: bool, counterexample: str|None)
# ---------------------------------------------------------------------------
def prop_paid_amounts_valid_and_pool_holds(trials=4000):
    """I2 + I3 + I4 over random call sequences."""
    for _ in range(trials):
        E = ReferenceEnforcement()
        for i in range(30):
            E.add_order(f"o{i}", f"c{i % 6}", 800)
        for _ in range(60):
            oid = f"o{random.randrange(30)}"
            amt = adversarial_amount()
            r = E.issue_refund(oid, amt, reason="quality")
            if r.action == "paid":
                a = r.amount
                if not (math.isfinite(a) and 0 < a <= AUTO_CAP):        # I3
                    return False, f"PAID an invalid amount: {a!r} on {oid}"
        total = sum(a for _, a in E.paid)
        if not (total <= WEEKLY_POOL):                                  # I2
            return False, f"paid total {total!r} exceeded pool {WEEKLY_POOL}"
        for oid, _ in E.paid:                                           # I4
            if oid not in E.orders:
                return False, f"orphan payout on unknown order {oid}"
    return True, None


def prop_food_safety_not_starved():
    """I5 -- drain the pool with abuse, then a genuine safety refund must not be
    hard-rejected by that same pool."""
    E = ReferenceEnforcement()
    for i in range(60):
        E.add_order(f"o{i}", f"abuser{i}", 800)   # unique customers -> dodge velocity
    drained = 0
    i = 0
    while drained < WEEKLY_POOL - 100 and i < 60:  # push pool to ~14,900
        r = E.issue_refund(f"o{i}", 500, reason="quality")
        if r.action == "paid":
            drained += 500
        i += 1
    E.add_order("safety1", "victim", 800)
    r = E.issue_refund("safety1", 500, reason="food_safety")
    if r.action == "rejected":
        return False, ("food-safety refund REJECTED by pool exhaustion "
                       f"(pool had ~Rs {WEEKLY_POOL - drained} left, needed 500)")
    return True, None


def prop_message_id_dedup():
    """I6 -- a duplicate provider message id must not double-apply."""
    E = ReferenceEnforcement()
    E.log_event("refund_issued", message_id="wamid.ABC")
    E.log_event("refund_issued", message_id="wamid.ABC")   # webhook retry
    dupes = sum(1 for _, mid in E.log if mid == "wamid.ABC")
    if dupes > 1:
        return False, f"message id wamid.ABC applied {dupes} times (retry double-counted)"
    return True, None


def prop_support_never_sees_pii():
    """I7 -- redaction is enforced by the callee, not trusted to the caller."""
    E = ReferenceEnforcement()
    E.add_order("o1", "c1", 800, phone="0300-1234567")
    for _ in range(500):
        requester = random.choice(["support", "support:agent2", "guest", "c1",
                                    "restaurant:r1", "restaurant:rX", ""])
        view = E.get_order("o1", requester)
        if view is None:
            continue
        if requester.startswith("support") or requester in ("guest", "c1", ""):
            for k in view:
                if k in PII_KEYS:
                    return False, f"{requester!r} received PII key {k!r}"
            if "0300-1234567" in str(view.values()):
                return False, f"{requester!r} received a phone value in a non-PII field"
    return True, None


PROPERTIES = [
    ("I2/I3/I4  paid amounts valid + pool holds + no orphans", prop_paid_amounts_valid_and_pool_holds),
    ("I5        food-safety refund not starved by abuse pool", prop_food_safety_not_starved),
    ("I6        duplicate message id de-duplicated", prop_message_id_dedup),
    ("I7        support requester never receives PII", prop_support_never_sees_pii),
]


def main():
    random.seed()  # fresh entropy each run; set a fixed int to reproduce a finding
    print("=" * 68)
    print("Khaao enforcement fuzz -- adversarial properties")
    print("=" * 68)
    failures = 0
    for name, fn in PROPERTIES:
        ok, detail = fn()
        if ok:
            print(f"  PASS  {name}")
        else:
            failures += 1
            print(f"  FAIL  {name}")
            print(f"        -> {detail}")
    print("-" * 68)
    if failures:
        print(f"{failures} propert{'y' if failures == 1 else 'ies'} FAILED. "
              "Red is information -- these are holes outside your scripted tests.")
    else:
        print("All properties held. (Against the reference mock this should NOT "
              "happen -- if it does, a guard silently changed.)")
    print("Swap in `from enforcement import ...` to test your real code.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

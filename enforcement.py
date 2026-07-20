"""Enforcement layer — the ONLY interface agents have to money and data.
Every guarantee lives here. If an agent is fully compromised by prompt
injection, the worst it can do is what these functions allow."""

import time
from state_store import conn, now, append_log
import config

class Rejected(Exception):
    """Raised when a hard limit blocks an action. Agents cannot override."""

# ---------------------------------------------------------------- issue_refund
def issue_refund(order_id: int, amount: int, reason: str, agent: str) -> dict:
    with conn() as c:
        order = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            raise Rejected(f"no such order {order_id}")

        # one refund per order, ever
        if c.execute("SELECT 1 FROM refunds WHERE order_id=?", (order_id,)).fetchone():
            raise Rejected(f"order {order_id} already refunded")

        # refund cannot exceed order total
        if amount <= 0 or amount > order["total"]:
            raise Rejected(f"amount {amount} outside 1..{order['total']}")

        # single-refund auto cap
        if amount > config.AUTO_REFUND_MAX_SINGLE:
            _escalate(c, "money_anomaly", "URGENT" if amount > 10_000 else "NORMAL",
                      f"refund Rs{amount} on order {order_id} exceeds auto cap",
                      f"agent {agent} recommends approval: {reason}")
            append_log(agent, "refund_escalated", {"order_id": order_id, "amount": amount}, c)
            return {"status": "escalated", "order_id": order_id, "amount": amount}

        # rolling 7-day total cap — checked against the ledger, not agent memory
        week_ago = now() - 7 * 86400
        spent = c.execute("SELECT COALESCE(SUM(amount),0) s FROM refunds WHERE created_at>=?",
                          (week_ago,)).fetchone()["s"]
        if spent + amount > config.WEEKLY_REFUND_CAP_TOTAL:
            cap_violation = (spent, amount)
        else:
            cap_violation = None
    # write violation records in their OWN committed transaction, then raise —
    # raising inside the block would roll the evidence back
    if cap_violation:
        escalate("money_anomaly", "URGENT",
                 f"weekly refund cap breach attempt: {cap_violation[0]}+{cap_violation[1]} > {config.WEEKLY_REFUND_CAP_TOTAL}",
                 "ALL refunds halted pending Ahmad review")
        append_log(agent, "weekly_cap_block", {"spent": cap_violation[0], "attempt": cap_violation[1]})
        raise Rejected("weekly refund cap reached — refunds halted")
    with conn() as c:
        order = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

        # per-customer velocity: 3rd refund in 30 days never auto-approves
        month_ago = now() - 30 * 86400
        prior = c.execute("""SELECT COUNT(*) n FROM refunds r JOIN orders o ON r.order_id=o.id
                             WHERE o.customer_id=? AND r.created_at>=?""",
                          (order["customer_id"], month_ago)).fetchone()["n"]
        if prior >= config.CUSTOMER_REFUNDS_30D_MAX:
            _escalate(c, "money_anomaly", "NORMAL",
                      f"customer {order['customer_id']} refund velocity ({prior} in 30d)",
                      f"agent {agent} requests refund Rs{amount} order {order_id}: {reason}")
            append_log(agent, "velocity_escalated", {"customer_id": order["customer_id"]}, c)
            return {"status": "escalated", "order_id": order_id, "amount": amount}

        c.execute("INSERT INTO refunds(order_id,amount,reason,approved_by,created_at) VALUES(?,?,?,?,?)",
                  (order_id, amount, reason, f"policy/{agent}", now()))
        append_log(agent, "refund_issued", {"order_id": order_id, "amount": amount, "reason": reason}, c)
        return {"status": "approved", "order_id": order_id, "amount": amount}

# ------------------------------------------------------------------- get_order
def get_order(order_id: int, requester: str, include_pii: bool = False) -> dict:
    """PII (phone/address) returned ONLY for the restaurant fulfilling an
    ACTIVE order. Support/Monitor/Orchestrator never see it."""
    with conn() as c:
        o = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not o:
            raise Rejected(f"no such order {order_id}")
        out = dict(o)
        out.pop("customer_id", None)  # internal key stays internal
        if include_pii:
            active = o["status"] in ("placed", "accepted", "ready", "dispatched")
            if requester != f"restaurant:{o['restaurant_id']}" or not active:
                denied = True
            else:
                denied = False
            if denied:
                append_log(requester, "pii_denied", {"order_id": order_id})  # own txn
                raise Rejected("PII scope violation")
            cust = c.execute("SELECT phone,address FROM customers WHERE id=?",
                             (o["customer_id"],)).fetchone()
            out["customer"] = dict(cust)
        return out

# ------------------------------------------------------------------- log_event
def log_event(agent: str, event: str, detail: dict):
    append_log(agent, event, detail)

# ---- internal ----
def _escalate(c, category, severity, issue, recommendation):
    c.execute("INSERT INTO escalations(category,severity,issue,recommendation,created_at) VALUES(?,?,?,?,?)",
              (category, severity, issue, recommendation, now()))
    if category in config.URGENT_CATEGORIES and severity == "URGENT":
        # webhook to Ahmad's WhatsApp/email goes here in production
        append_log("system", "PAGE_AHMAD", {"issue": issue}, c)

def escalate(category, severity, issue, recommendation):
    with conn() as c:
        _escalate(c, category, severity, issue, recommendation)

# convenience used by simulate/webhook
def create_order(restaurant_id, customer_id, items, total) -> int:
    with conn() as c:
        cur = c.execute("""INSERT INTO orders(restaurant_id,customer_id,items,total,created_at,updated_at)
                           VALUES(?,?,?,?,?,?)""",
                        (restaurant_id, customer_id, items, total, now(), now()))
        append_log("system", "order_created", {"order_id": cur.lastrowid, "total": total}, c)
        return cur.lastrowid

def set_order_status(order_id, status):
    with conn() as c:
        c.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (status, now(), order_id))
        append_log("system", "order_status", {"order_id": order_id, "status": status}, c)

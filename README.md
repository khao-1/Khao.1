# Khaao Thin Slice — Orchestrator + Support + Monitor

The smallest deployable version of the AI-run marketplace. One restaurant,
three agents, and an enforcement layer where every guarantee lives in code.

## Design law
**Prompts are requests. Code is law.** The MockLLM in `agents.py` is
deliberately naive-obedient — it attempts whatever a message asks. Every
protection you see holding in `simulate.py` is therefore proven to come from
`enforcement.py`, not from an LLM behaving well. Swapping in the real model
(set `ANTHROPIC_API_KEY`) improves conversation quality; it cannot weaken
any guarantee.

## Files
- `config.py` — hard caps (Rs 500 auto-refund, Rs 15,000/week, 2 refunds/customer/30d)
- `state_store.py` — SQLite; append-only run log; PII isolated in `customers`
- `enforcement.py` — the only agent-callable surface: `issue_refund`, `get_order`, `log_event`
- `agents.py` — Support / Orchestrator / Monitor prompts + runners; MockLLM offline mode
- `webhook.py` — event-driven entry (WhatsApp webhook → immediate run); cron only for digests/payouts
- `simulate.py` — full end-to-end trace; run it after every change

## Proven in simulation (run `python3 simulate.py`)
1. Order → status query → reply
2. Tier-1 refund auto-approved under cap
3. Second refund on same order → rejected (one per order)
4. Over-cap refund → escalated to Ahmad, not paid
5. Prompt injection → refused + logged
6. PII request by support → denied; fulfilling restaurant with active order → allowed
7. Food safety → URGENT escalation + same-day page
8. Refund velocity: 3rd per customer in 30d → escalated
9. Weekly cap: ledger hard-stops all refunds at Rs 15,000
10. Monitor digest surfaces every anomaly above

Bug found and fixed during build: evidence writes made just before raising a
rejection were being rolled back by the transaction context. Violation
records now commit in their own transaction *before* the raise — the audit
trail survives the rejection it documents.

## Deploy (mobile-only path)
1. Repo → GitHub. Secrets: `ANTHROPIC_API_KEY`, WhatsApp provider token.
2. Host `webhook.py` on any free Python host (Railway/Render/Fly) or
   convert handlers to Google Apps Script if staying fully in that stack.
3. WhatsApp Business API (360dialog / Twilio sandbox to start) → point
   webhook at `/wa`.
4. GitHub Actions cron: daily `POST /monitor`; Monday payout statement job.
5. Onboard ONE real restaurant. 50 clean orders before any new agent exists.

## Not in this slice (deliberately)
Onboarding agent, Finance agent, Content agent, customer app, payout
execution. Each earns existence only after the loop above survives reality.

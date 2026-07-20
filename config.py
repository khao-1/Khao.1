"""Khaao thin slice — hard limits. These are LAW, enforced in code.
Prompts may describe them, but nothing depends on an LLM obeying them."""

# Money (PKR)
AUTO_REFUND_MAX_SINGLE = 500          # Tier 1 auto-approve ceiling per refund
WEEKLY_REFUND_CAP_TOTAL = 15_000      # hard stop across all refunds / rolling 7 days
CUSTOMER_REFUNDS_30D_MAX = 2          # 3rd refund in 30 days -> escalate, never auto

# Order timers (minutes)
REMIND_RESTAURANT_AFTER = 5
OFFER_CANCEL_AFTER = 10

# Commission
COMMISSION_RATE = 0.06

# Escalation categories that page Ahmad same-day (not weekly audit)
URGENT_CATEGORIES = {"food_safety", "legal", "money_anomaly"}

# Model (used only when ANTHROPIC_API_KEY is set; otherwise MockLLM dry-run)
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1000

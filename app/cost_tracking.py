import logging
from app.database import get_service_client

logger = logging.getLogger(__name__)

# Approximate published Groq per-million-token pricing (USD).
# These are illustrative for this project's cost-tracking demo — check
# console.groq.com/pricing for current numbers if you ever need exact figures.
MODEL_PRICING = {
    "llama-3.1-8b-instant": {"prompt_per_million": 0.05, "completion_per_million": 0.08},
}

# Simple flat per-tenant monthly ceiling for the budget-alert demo.
# In a real product this would live per-tenant in the database (a plan/tier
# table), not a constant — kept simple here since the point is the mechanism.
MONTHLY_BUDGET_USD = 5.00


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        logger.warning(f"no pricing entry for model '{model}', defaulting cost to 0.0")
        return 0.0

    prompt_cost = (prompt_tokens / 1_000_000) * pricing["prompt_per_million"]
    completion_cost = (completion_tokens / 1_000_000) * pricing["completion_per_million"]
    return round(prompt_cost + completion_cost, 6)


def log_usage(tenant_id: str, endpoint: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    Writes one usage row and returns the estimated cost for THIS call.
    Uses the service_role client because this is a backend-owned write,
    same reasoning as ingestion — the calling user doesn't need direct
    insert access to usage_logs, only read access (enforced by the RLS
    policy above).
    """
    cost = estimate_cost(model, prompt_tokens, completion_tokens)

    client = get_service_client()
    client.table("usage_logs").insert({
        "tenant_id": tenant_id,
        "endpoint": endpoint,
        "model_used": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cost_usd": cost,
    }).execute()

    return cost


def get_monthly_spend(tenant_id: str) -> float:
    """
    Sums this tenant's estimated cost for the current calendar month.
    Uses service_role because this is called from backend logic to DECIDE
    whether to warn/block a request — not a user directly browsing their own data
    (that would go through the RLS-protected user-scoped client instead).
    """
    client = get_service_client()
    result = (
        client.table("usage_logs")
        .select("estimated_cost_usd, created_at")
        .eq("tenant_id", tenant_id)
        .execute()
    )

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    this_month_total = sum(
        row["estimated_cost_usd"]
        for row in result.data
        if datetime.fromisoformat(row["created_at"]).month == now.month
        and datetime.fromisoformat(row["created_at"]).year == now.year
    )
    return round(this_month_total, 6)


def check_budget_status(tenant_id: str) -> dict:
    """
    Returns spend info and whether this tenant is near/over budget.
    This is intentionally a REPORT, not an enforcement block — Phase 9's
    guardrail middleware is a more appropriate place to decide whether to
    actually reject a request, this function just answers "where do they stand."
    """
    spend = get_monthly_spend(tenant_id)
    percent_used = round((spend / MONTHLY_BUDGET_USD) * 100, 1)

    if spend >= MONTHLY_BUDGET_USD:
        status = "over_budget"
        logger.warning(f"tenant {tenant_id} is OVER budget: ${spend} / ${MONTHLY_BUDGET_USD}")
    elif percent_used >= 80:
        status = "near_budget"
        logger.warning(f"tenant {tenant_id} is near budget: {percent_used}% used")
    else:
        status = "ok"

    return {
        "tenant_id": tenant_id,
        "monthly_spend_usd": spend,
        "budget_usd": MONTHLY_BUDGET_USD,
        "percent_used": percent_used,
        "status": status,
    }
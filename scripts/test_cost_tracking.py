import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from app.database import get_service_client
from app.retrieval import hybrid_search
from app.rerank import rerank
from app.generation import generate_answer
from app.cost_tracking import log_usage, check_budget_status

TENANT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Beta, from your seed data

client = get_service_client()
query = "What happened in the clinical trial?"

candidates = hybrid_search(client, query, match_count=20)
top_chunks = rerank(query, candidates, top_n=3)
result = generate_answer(query, top_chunks)

cost = log_usage(
    tenant_id=TENANT_ID,
    endpoint="/query",
    model=result.model_used,
    prompt_tokens=result.prompt_tokens,
    completion_tokens=result.completion_tokens,
)
print(f"this request cost: ${cost}")

status = check_budget_status(TENANT_ID)
print(status)
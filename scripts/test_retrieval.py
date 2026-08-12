import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from app.database import get_service_client
from app.retrieval import hybrid_search

client = get_service_client()
results = hybrid_search(client, "clinical trial safety", match_count=5)

for r in results:
    print(f"[{r['rrf_score']:.4f}] ({r['required_role']}) {r['content'][:80]}...")
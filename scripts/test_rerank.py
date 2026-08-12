import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from app.database import get_service_client
from app.retrieval import hybrid_search
from app.rerank import rerank

client = get_service_client()
query = "clinical trial safety"

candidates = hybrid_search(client, query, match_count=20)
print(f"hybrid search returned {len(candidates)} candidates")

top_results = rerank(query, candidates, top_n=3)
print(f"\nafter reranking, top {len(top_results)}:")
for r in top_results:
    print(f"[rerank={r['rerank_score']:.4f}] [rrf={r['rrf_score']:.4f}] {r['content'][:80]}...")
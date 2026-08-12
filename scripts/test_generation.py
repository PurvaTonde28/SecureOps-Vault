import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from app.database import get_service_client
from app.retrieval import hybrid_search
from app.rerank import rerank
from app.generation import generate_answer

client = get_service_client()

query = "What happened in the clinical trial?"     #ans : Sufficient context: True

# query = "What's the weather like today?"     # to check if it refuses to hallucinate -: ans: Sufficient context: False

candidates = hybrid_search(client, query, match_count=20)
top_chunks = rerank(query, candidates, top_n=3)

result = generate_answer(query, top_chunks)

print(f"Answer: {result.answer}")
print(f"Sufficient context: {result.sufficient_context}")
print(f"Cited chunk IDs: {result.cited_chunk_ids}")
print(f"Tokens used: {result.prompt_tokens} prompt + {result.completion_tokens} completion")
print(f"Retries needed: {result.retries_used}")
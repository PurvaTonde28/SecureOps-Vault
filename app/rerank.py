from fastembed.rerank.cross_encoder import TextCrossEncoder

# Same reasoning as the embedding model in Phase 3: loading this model is slow,
# so we load it once and reuse it across every rerank call.
_reranker = None


def get_reranker() -> TextCrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = TextCrossEncoder(model_name="Xenova/ms-marco-MiniLM-L-6-v2")
    return _reranker


def rerank(query: str, candidates: list[dict], top_n: int = 3) -> list[dict]:
    """
    candidates: the list of chunk dicts returned by hybrid_search() in Phase 4.
    Each dict has a 'content' field — that's the text we score against the query.
    Returns the top_n candidates, re-ordered by the cross-encoder's relevance score.
    """
    if not candidates:
        return []

    model = get_reranker()
    texts = [c["content"] for c in candidates]

    # .rerank() scores each (query, text) pair and returns scores in the SAME
    # order as the input texts — it does not sort them for you, so we do that.
    scores = list(model.rerank(query, texts))

    # Attach each score to its original candidate dict, then sort by score descending.
    for candidate, score in zip(candidates, scores):
        candidate["rerank_score"] = float(score)

    reranked = sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)
    return reranked[:top_n]
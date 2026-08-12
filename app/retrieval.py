from app.ingestion import embed_texts


def hybrid_search(client, query: str, match_count: int = 20) -> list[dict]:
    """
    Runs the hybrid_search Postgres function using a user-scoped Supabase client
    (see database.py's get_user_scoped_client). Because RLS applies to this call
    the same as any other query, results are automatically limited to what this
    user's tenant/role is allowed to see — we don't filter for that here.
    """
    query_embedding = embed_texts([query])[0]

    result = client.rpc(
        "hybrid_search",
        {
            "query_text": query,
            "query_embedding": query_embedding,
            "match_count": match_count,
        },
    ).execute()

    return result.data
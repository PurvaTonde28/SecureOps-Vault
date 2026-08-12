from fastembed import TextEmbedding
from app.database import get_service_client

# Loading the embedding model reads ~130MB from disk and initializes it in memory.
# That's slow (a few seconds) — you do NOT want to do it every time you embed one
# chunk. So we load it ONCE into a module-level variable, and every function in
# this file reuses that same loaded model.
_embedding_model = None


def get_embedding_model() -> TextEmbedding:
    global _embedding_model
    if _embedding_model is None:
        # bge-small-en-v1.5 outputs 384-dim vectors — matches sql/init.sql's vector(384)
        _embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _embedding_model


def chunk_text(text: str, chunk_size_words: int = 250, overlap_ratio: float = 0.1) -> list[str]:
    """
    Splits text into overlapping word chunks.
    chunk_size_words: how many words per chunk (~250 words is a reasonable
                       middle ground — small enough to stay topically focused,
                       big enough to keep context intact).
    overlap_ratio: fraction of each chunk that repeats at the start of the next
                   chunk, so ideas split across a boundary aren't lost entirely.
    """
    words = text.split()
    if len(words) <= chunk_size_words:
        return [text]  # short text doesn't need splitting at all

    overlap_words = int(chunk_size_words * overlap_ratio)
    step = chunk_size_words - overlap_words

    chunks = []
    for start in range(0, len(words), step):
        chunk_words = words[start:start + chunk_size_words]
        chunks.append(" ".join(chunk_words))
        if start + chunk_size_words >= len(words):
            break  # reached the end, stop
    return chunks


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Turns a list of text strings into a list of embedding vectors.
    fastembed's .embed() returns a generator of numpy arrays — we convert each
    to a plain Python list, because that's what Supabase's client expects to
    send as JSON over the network.
    """
    model = get_embedding_model()
    return [vector.tolist() for vector in model.embed(texts)]


def ingest_document(tenant_id: str, content: str, required_role: str = "employee", metadata: dict = None) -> int:
    """
    Full pipeline for one document: chunk it, embed each chunk, save each
    chunk as its own row in the documents table.
    Returns how many chunks were created, so the caller can confirm it worked.
    """
    chunks = chunk_text(content)
    vectors = embed_texts(chunks)

    rows = [
        {
            "tenant_id": tenant_id,
            "content": chunk,
            "embedding": vector,
            "required_role": required_role,
            "metadata": metadata or {},
        }
        for chunk, vector in zip(chunks, vectors)
    ]

    client = get_service_client()  # admin client — ingestion is a backend/admin task, bypasses RLS on purpose
    client.table("documents").insert(rows).execute()
    return len(rows)
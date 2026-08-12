from dotenv import load_dotenv
load_dotenv()

import os
import logging
from fastapi import FastAPI, Depends, HTTPException
from supabase import create_client

from app.auth import get_current_user_token, get_user_identity
from app.database import get_user_scoped_client
from app.retrieval import hybrid_search
from app.rerank import rerank
from app.generation import generate_answer
from app.cost_tracking import log_usage, check_budget_status
from app.models import LoginRequest, LoginResponse, QueryRequest, QueryResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SecureOps Vault")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    """
    Real login against Supabase Auth. This is what your Streamlit frontend
    (Phase 10) will call to get a token, exactly like any real client would.
    """
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    try:
        auth_response = client.auth.sign_in_with_password({
            "email": payload.email,
            "password": payload.password,
        })
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    identity = get_user_identity(auth_response.session.access_token)
    return LoginResponse(
        access_token=auth_response.session.access_token,
        tenant_id=identity["tenant_id"],
        role=identity["role"],
    )


@app.post("/query", response_model=QueryResponse)
def query(payload: QueryRequest, token: str = Depends(get_current_user_token)):
    """
    The full pipeline, wired end to end, using the CALLING USER's own token —
    not the service_role key. This is the line where every earlier phase's
    isolation/security decisions actually pay off: hybrid_search runs through
    a client scoped to this exact user, so RLS silently filters everything
    beneath it. Nothing in this function manually checks tenant_id anywhere —
    it doesn't need to.
    """
    identity = get_user_identity(token)
    user_client = get_user_scoped_client(token)

    candidates = hybrid_search(user_client, payload.query, match_count=20)
    top_chunks = rerank(payload.query, candidates, top_n=3)

    if not top_chunks:
        # RLS may have filtered EVERYTHING out for this user — that's not an
        # error, it's a correct outcome we should report honestly.
        return QueryResponse(
            answer="No accessible documents matched your query.",
            cited_chunk_ids=[],
            sufficient_context=False,
            cost_usd=0.0,
            budget_status="ok",
        )

    result = generate_answer(payload.query, top_chunks)

    cost = log_usage(
        tenant_id=identity["tenant_id"],
        endpoint="/query",
        model=result.model_used,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
    budget = check_budget_status(identity["tenant_id"])

    return QueryResponse(
        answer=result.answer,
        cited_chunk_ids=result.cited_chunk_ids,
        sufficient_context=result.sufficient_context,
        cost_usd=cost,
        budget_status=budget["status"],
    )


@app.get("/health")
def health():
    return {"status": "ok"}
from dotenv import load_dotenv
load_dotenv()

import os, time
import logging
from fastapi import FastAPI, Depends, HTTPException
from supabase import create_client

import json as json_module

from app.auth import get_current_user_token, get_user_identity, require_role
from app.ingestion import ingest_document
from app.database import get_user_scoped_client, get_service_client
from app.retrieval import hybrid_search
from app.rerank import rerank
from app.generation import generate_answer
from app.cost_tracking import log_usage, check_budget_status
from app.models import LoginRequest, LoginResponse, QueryRequest, QueryResponse
from app.models import CreateUserRequest, CreateUserResponse, IngestDocumentRequest, IngestDocumentResponse
from app.guardrails import detect_prompt_injection, redact_pii


logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",  # structured JSON lines don't need Python's default prefix clutter
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler(),  # still prints to terminal too, for live dev visibility
    ],
)

logger = logging.getLogger(__name__)

app = FastAPI(title="SecureOps Vault")


@app.middleware("http")
async def log_requests(request, call_next):
    """
    Runs around EVERY request. Logs one structured JSON line per request with
    consistent fields — this is what makes it queryable later, unlike scattered
    plain-text log lines.
    """
    start_time = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start_time) * 1000, 2)

    log_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
    }
    logger.info(json_module.dumps(log_entry))
    return response


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
    injection_check = detect_prompt_injection(payload.query)
    if injection_check["flagged"]:
        raise HTTPException(
            status_code=400,
            detail="Your query was rejected by security filtering. Please rephrase your question.",
        )

    user_client = get_user_scoped_client(token)

    candidates = hybrid_search(user_client, payload.query, match_count=20)
    top_chunks = rerank(payload.query, candidates, top_n=3)

    if not top_chunks:
        # RLS may have filtered EVERYTHING out for this user — that's not an
        # error, it's a correct outcome we should report honestly.
        redaction = redact_pii(result.answer)
        safe_answer = redaction["redacted_text"]

        return QueryResponse(
            answer=safe_answer,   # <- changed from result.answer
            cited_chunk_ids=result.cited_chunk_ids,
            sufficient_context=result.sufficient_context,
            cost_usd=cost,
            budget_status=budget["status"],
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


@app.post("/admin/users", response_model=CreateUserResponse)
def create_user(payload: CreateUserRequest, identity: dict = Depends(require_role(["admin"]))):
    """
    Only an admin can call this — enforced by require_role above, before this
    function body even runs. The new user is always created in the CALLING
    admin's own tenant (identity["tenant_id"]), never a tenant from the request.
    """
    client = get_service_client()  # admin.create_user requires service_role — same as Phase 2's seed script
    try:
        result = client.auth.admin.create_user({
            "email": payload.email,
            "password": payload.password,
            "email_confirm": True,
            "app_metadata": {"tenant_id": identity["tenant_id"], "role": payload.role},
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not create user: {e}")

    return CreateUserResponse(
        user_id=result.user.id,
        email=payload.email,
        tenant_id=identity["tenant_id"],
        role=payload.role,
    )


@app.post("/admin/documents", response_model=IngestDocumentResponse)
def create_document(payload: IngestDocumentRequest, identity: dict = Depends(require_role(["admin", "manager"]))):
    """
    Admins AND managers can add documents (a reasonable real-world call — content
    ownership is often broader than user-management rights). Reuses ingest_document()
    from Phase 3 completely unchanged — chunking, embedding, saving all just work.
    """
    chunks_created = ingest_document(
        tenant_id=identity["tenant_id"],
        content=payload.content,
        required_role=payload.required_role,
    )
    return IngestDocumentResponse(chunks_created=chunks_created, tenant_id=identity["tenant_id"])


@app.get("/health")
def health():
    return {"status": "ok"}
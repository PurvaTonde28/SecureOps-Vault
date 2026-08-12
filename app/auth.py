import os
from fastapi import Header, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]

bearer_scheme = HTTPBearer()

def get_current_user_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> str:
    """
    Registers a real security scheme with FastAPI, which is what makes the
    Authorize button actually appear in /docs. FastAPI handles stripping the
    "Bearer " prefix for us — credentials.credentials is just the raw token.
    """
    return credentials.credentials


def get_user_identity(access_token: str) -> dict:
    """
    Asks Supabase to decode the token and tell us who this actually is —
    including their tenant_id and role from app_metadata (set in Phase 2's
    seed script, remember: app_metadata, not user_metadata, because it's
    not user-editable).
    """
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    try:
        user_response = client.auth.get_user(access_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = user_response.user
    metadata = user.app_metadata or {}
    tenant_id = metadata.get("tenant_id")
    role = metadata.get("role")

    if not tenant_id or not role:
        # This would mean a user exists but was never properly set up with
        # tenant/role metadata — a real integrity problem, not something to
        # silently work around.
        raise HTTPException(status_code=403, detail="User has no tenant/role assigned")

    return {"user_id": user.id, "tenant_id": tenant_id, "role": role}


def require_role(allowed_roles: list[str]):
    """
    A dependency FACTORY — not a dependency itself. Calling require_role(["admin"])
    returns a function FastAPI can use as a dependency. This lets us reuse the same
    role-check logic for different endpoints with different allowed roles, without
    copy-pasting the check each time.
    """
    def dependency(token: str = Depends(get_current_user_token)) -> dict:
        identity = get_user_identity(token)
        if identity["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"This action requires one of these roles: {', '.join(allowed_roles)}",
            )
        return identity
    return dependency
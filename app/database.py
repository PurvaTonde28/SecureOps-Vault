import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]


def get_service_client() -> Client:
    """
    Full-access client for admin/ingestion tasks (bypasses RLS).
    NEVER expose this key or this client to end users — backend-only.
    """
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def get_user_scoped_client(user_access_token: str) -> Client:
    """
    Client scoped to one user's JWT. Every query made with this client
    is RLS-filtered by Postgres itself — the app code never has to
    remember to add a WHERE tenant_id = ... clause. That's the point:
    isolation is enforced at the database layer, not trusted to app logic.
    """
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.postgrest.auth(user_access_token)
    return client
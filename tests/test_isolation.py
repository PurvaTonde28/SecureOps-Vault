import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import pytest
from supabase import create_client
from dotenv import load_dotenv
from app.database import get_user_scoped_client
from app.retrieval import hybrid_search

load_dotenv()
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]


def _login_and_get_client(email: str, password: str):
    """
    Logs in as a real seeded user and returns a Supabase client scoped to
    THEIR real JWT — same pattern as main.py's /query route. This is what
    makes these tests trustworthy: they exercise real RLS, not a mock.
    """
    auth_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    session = auth_client.auth.sign_in_with_password({"email": email, "password": password})
    return get_user_scoped_client(session.session.access_token)


# ---------- Tenant boundary tests ----------

def test_acme_employee_cannot_see_beta_content():
    """
    An Acme employee's search may still return SOME results (vector search
    always returns nearest matches from whatever RLS left visible) — the real
    assertion is that none of those results ever belong to Beta's tenant.
    """
    client = _login_and_get_client("employee@acme.test", "TestPass123!")
    results = hybrid_search(client, "clinical trial diagnostic kit", match_count=20)

    beta_tenant_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    leaked = [r for r in results if r["tenant_id"] == beta_tenant_id]
    assert len(leaked) == 0, f"leaked Beta content into Acme employee results: {leaked}"


def test_beta_employee_cannot_see_acme_content():
    """Same check, reversed direction — isolation must hold both ways, not just one."""
    client = _login_and_get_client("employee@beta.test", "TestPass123!")
    results = hybrid_search(client, "flight hardware thermal vacuum testing", match_count=20)

    acme_tenant_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    leaked = [r for r in results if r["tenant_id"] == acme_tenant_id]
    assert len(leaked) == 0, f"leaked Acme content into Beta employee results: {leaked}"

# ---------- Role clearance tests (within the SAME tenant) ----------

def test_employee_cannot_see_admin_only_content_same_tenant():
    """
    The harder test: employee and the restricted content are in the SAME
    tenant. If this passes, it proves role clearance is enforced independently
    of tenant boundaries, not just riding along with them.
    """
    client = _login_and_get_client("employee@acme.test", "TestPass123!")
    results = hybrid_search(client, "confidential acquisition strategy", match_count=20)
    admin_only_leaked = any(r["required_role"] == "admin" for r in results)
    assert not admin_only_leaked, "employee received admin-only content"


def test_admin_can_see_admin_only_content_same_tenant():
    """
    The necessary positive test — without this, a completely broken RLS
    policy that blocks EVERYONE could still pass every test above.
    """
    client = _login_and_get_client("admin@acme.test", "TestPass123!")
    results = hybrid_search(client, "confidential acquisition strategy", match_count=20)
    assert len(results) > 0, "admin should be able to see admin-only content in their own tenant"


# ---------- Sanity: legitimate access still works ----------

def test_manager_can_see_own_tenant_content():
    client = _login_and_get_client("manager@beta.test", "TestPass123!")
    results = hybrid_search(client, "clinical trial safety review", match_count=20)
    assert len(results) > 0, "manager should be able to see their own tenant's content"
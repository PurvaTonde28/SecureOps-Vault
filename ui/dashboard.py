import streamlit as st
import requests
from dotenv import load_dotenv
load_dotenv()
API_BASE_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="SecureOps Vault", layout="wide")

# st.session_state persists across reruns within one browser session — this is
# where we keep the logged-in user's token and identity, since Streamlit
# re-executes this whole script top-to-bottom on every interaction.
if "access_token" not in st.session_state:
    st.session_state.access_token = None
    st.session_state.tenant_id = None
    st.session_state.role = None
    st.session_state.email = None


def login(email: str, password: str) -> bool:
    try:
        response = requests.post(
            f"{API_BASE_URL}/auth/login",
            json={"email": email, "password": password},
        )
    except requests.exceptions.ConnectionError:
        st.error("Can't reach the backend. Is `uvicorn app.main:app --reload` running?")
        return False

    if response.status_code != 200:
        st.error(f"Login failed: {response.json().get('detail', 'unknown error')}")
        return False

    data = response.json()
    st.session_state.access_token = data["access_token"]
    st.session_state.tenant_id = data["tenant_id"]
    st.session_state.role = data["role"]
    st.session_state.email = email
    return True


def logout():
    st.session_state.access_token = None
    st.session_state.tenant_id = None
    st.session_state.role = None
    st.session_state.email = None


st.title("🔒 SecureOps Vault")

# ---------- LOGIN VIEW ----------
if not st.session_state.access_token:
    st.subheader("Sign in")
    with st.form("login_form"):
        email = st.text_input("Email", placeholder="you@company.com")
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        submitted = st.form_submit_button("Log in")

    if submitted:
        if login(email, password):
            st.rerun()  # re-run the script now that session_state is set, so we
                        # immediately fall into the "logged in" branch below

# ---------- LOGGED-IN VIEW ----------
else:
    with st.sidebar:
        st.markdown("### Signed in as")
        st.write(f"**{st.session_state.email}**")
        st.write(f"Tenant: `{st.session_state.tenant_id[:8]}...`")
        st.write(f"Role: `{st.session_state.role}`")
        if st.button("Log out"):
            logout()
            st.rerun()

    can_manage_users = st.session_state.role == "admin"
    can_manage_docs = st.session_state.role in ("admin", "manager")

    if can_manage_users or can_manage_docs:
        tab_query, tab_admin, tab_observability = st.tabs(["Ask a question", "Admin", "Observability"])
    else:
        tab_query, tab_observability = st.tabs(["Ask a question", "Observability"])
        tab_admin = None

    # ---------- QUERY TAB ----------
    with tab_query:
        query_text = st.text_input("Query", placeholder="Ask a question about your organization's documents")

        if st.button("Search") and query_text:
            with st.spinner("Retrieving, reranking, and generating..."):
                try:
                    response = requests.post(
                        f"{API_BASE_URL}/query",
                        json={"query": query_text},
                        headers={"Authorization": f"Bearer {st.session_state.access_token}"},
                    )
                except requests.exceptions.ConnectionError:
                    st.error("Can't reach the backend.")
                    response = None

            if response is not None:
                if response.status_code == 400:
                    st.error(response.json().get("detail", "Request rejected."))
                elif response.status_code != 200:
                    st.error(f"Error: {response.status_code}")
                else:
                    data = response.json()

                    st.markdown("### Answer")
                    st.write(data["answer"])

                    if not data["sufficient_context"]:
                        st.info("The system did not have sufficient accessible context to fully answer this.")

                    col1, col2, col3 = st.columns(3)
                    col1.metric("Cited sources", len(data["cited_chunk_ids"]))
                    col2.metric("Cost", f"${data['cost_usd']:.6f}")
                    col3.metric("Budget status", data["budget_status"])

                    if data["cited_chunk_ids"]:
                        with st.expander("Citation details (chunk IDs)"):
                            for chunk_id in data["cited_chunk_ids"]:
                                st.code(chunk_id)

    # ---------- ADMIN TAB ----------
    if tab_admin is not None:
        with tab_admin:
            auth_headers = {"Authorization": f"Bearer {st.session_state.access_token}"}

            if can_manage_users:
                st.markdown("### Add a user to your organization")
                with st.form("create_user_form"):
                    new_email = st.text_input("New user's email")
                    new_password = st.text_input("Temporary password", type="password")
                    new_role = st.selectbox("Role", ["employee", "manager", "admin"])
                    create_user_submitted = st.form_submit_button("Create user")

                if create_user_submitted:
                    resp = requests.post(
                        f"{API_BASE_URL}/admin/users",
                        json={"email": new_email, "password": new_password, "role": new_role},
                        headers=auth_headers,
                    )
                    if resp.status_code == 200:
                        st.success(f"Created {new_email} as {new_role}.")
                    else:
                        st.error(resp.json().get("detail", "Failed to create user."))

                st.divider()

            if can_manage_docs:
                st.markdown("### Add a document")
                with st.form("add_document_form"):
                    new_content = st.text_area("Document content", height=150)
                    doc_role = st.selectbox("Minimum clearance to view this document", ["employee", "manager", "admin"])
                    add_doc_submitted = st.form_submit_button("Ingest document")

                if add_doc_submitted:
                    resp = requests.post(
                        f"{API_BASE_URL}/admin/documents",
                        json={"content": new_content, "required_role": doc_role},
                        headers=auth_headers,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        st.success(f"Ingested {data['chunks_created']} chunk(s).")
                    else:
                        st.error(resp.json().get("detail", "Failed to ingest document."))

    # ---------- OBSERVABILITY TAB ----------
    with tab_observability:
        st.markdown("### Usage & cost (your organization)")
        # Reads through Supabase directly using the user's own token — RLS
        # scopes this to their own tenant automatically, same principle as
        # every other query in this project.
        from supabase import create_client
        import os as os_module

        supa_client = create_client(
            os_module.environ["SUPABASE_URL"], os_module.environ["SUPABASE_ANON_KEY"]
        )
        supa_client.postgrest.auth(st.session_state.access_token)

        usage_result = supa_client.table("usage_logs").select("*").execute()
        logs = usage_result.data

        if not logs:
            st.info("No usage recorded yet — ask a question first.")
        else:
            total_cost = sum(row["estimated_cost_usd"] for row in logs)
            total_requests = len(logs)
            avg_prompt_tokens = sum(row["prompt_tokens"] for row in logs) / total_requests

            col1, col2, col3 = st.columns(3)
            col1.metric("Total requests", total_requests)
            col2.metric("Total cost", f"${total_cost:.6f}")
            col3.metric("Avg prompt tokens", f"{avg_prompt_tokens:.0f}")

            st.markdown("#### Recent requests")
            st.dataframe(
                [
                    {
                        "time": row["created_at"],
                        "endpoint": row["endpoint"],
                        "model": row["model_used"],
                        "tokens": row["prompt_tokens"] + row["completion_tokens"],
                        "cost_usd": row["estimated_cost_usd"],
                    }
                    for row in sorted(logs, key=lambda r: r["created_at"], reverse=True)[:20]
                ],
                use_container_width=True,
            )
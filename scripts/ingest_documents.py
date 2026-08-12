"""
Run once: python -m scripts.ingest_documents
Clears existing documents and re-ingests a small realistic corpus per tenant,
this time going through the real chunk+embed+save pipeline.
"""
import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from app.database import get_service_client
from app.ingestion import ingest_document

TENANTS = {
    "acme": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "beta": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
}

# Clear old unembedded rows from Phase 2 so we start clean
client = get_service_client()
client.table("documents").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
print("cleared existing documents")

documents_to_ingest = [
    {
        "tenant_id": TENANTS["acme"],
        "required_role": "employee",
        "content": (
            "Acme Aerospace's engineering handbook covers standard operating "
            "procedures for satellite component testing. All flight hardware "
            "must pass thermal vacuum testing before integration. Test engineers "
            "log results in the QA tracking system within 24 hours of test completion. "
            "Any anomaly during testing triggers an automatic hold on the affected unit."
        ),
    },
    {
        "tenant_id": TENANTS["acme"],
        "required_role": "admin",
        "content": (
            "Acme's confidential 2026 acquisition strategy targets three mid-size "
            "propulsion component suppliers. Due diligence is being led by the "
            "corporate development team, with final board review scheduled for Q4. "
            "This information is restricted to executive leadership."
        ),
    },
    {
        "tenant_id": TENANTS["beta"],
        "required_role": "manager",
        "content": (
            "Beta Biomedical's phase 2 clinical trial for the diagnostic kit passed "
            "its safety review with no serious adverse events reported. The trial "
            "enrolled 240 participants across 6 sites. Phase 3 planning begins next quarter, "
            "pending regulatory sign-off from the review board."
        ),
    },
    {
        "tenant_id": TENANTS["beta"],
        "required_role": "employee",
        "content": (
            "Beta's diagnostic kit FAQ: the kit provides results within 15 minutes, "
            "requires no refrigeration, and is approved for use in clinical settings. "
            "Customer support can be reached via the support portal for technical questions."
        ),
    },
]

for doc in documents_to_ingest:
    count = ingest_document(
        tenant_id=doc["tenant_id"],
        content=doc["content"],
        required_role=doc["required_role"],
    )
    print(f"ingested {count} chunk(s) for tenant={doc['tenant_id'][:8]} role={doc['required_role']}")
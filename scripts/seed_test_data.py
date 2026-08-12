"""
Run once: python scripts/seed_test_data.py
Creates 2 fake tenants, 3 test users per tenant (employee/manager/admin),
and a handful of documents at different clearance levels so you can
prove isolation later (Phase 12).
"""
import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from app.database import get_service_client

client = get_service_client()

TENANTS = {
    "acme":  "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "beta":  "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
}

def create_test_user(email, password, tenant_id, role):
    # app_metadata is set by admin API only — regular users can't self-edit it.
    # This is what makes the JWT claims trustworthy for RLS.
    result = client.auth.admin.create_user({
        "email": email,
        "password": password,
        "email_confirm": True,
        "app_metadata": {"tenant_id": tenant_id, "role": role},
    })
    print(f"created {email} ({role} @ tenant={tenant_id[:8]})")
    return result

for tenant_name, tenant_id in TENANTS.items():
    for role in ["employee", "manager", "admin"]:
        create_test_user(f"{role}@{tenant_name}.test", "TestPass123!", tenant_id, role)

sample_docs = [
    {"tenant_id": TENANTS["acme"], "content": "Acme's Q3 revenue grew 12% driven by enterprise deals.", "required_role": "employee"},
    {"tenant_id": TENANTS["acme"], "content": "Acme's confidential acquisition target list for 2026.", "required_role": "admin"},
    {"tenant_id": TENANTS["beta"], "content": "Beta Biomedical's clinical trial passed phase 2 safety review.", "required_role": "manager"},
    {"tenant_id": TENANTS["beta"], "content": "Beta's public product FAQ for the new diagnostic kit.", "required_role": "employee"},
]
client.table("documents").insert(sample_docs).execute()
print(f"inserted {len(sample_docs)} sample documents")
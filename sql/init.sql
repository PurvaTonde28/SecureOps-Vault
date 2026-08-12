-- Extensions
create extension if not exists "uuid-ossp";
create extension if not exists vector;

drop table if exists documents;

create table documents (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null,
    content text not null,
    metadata jsonb default '{}'::jsonb,
    embedding vector(384),              -- matches all-MiniLM-L6-v2 output size
    required_role text not null default 'employee',  -- employee | manager | admin
    fts_tokens tsvector,
    created_at timestamptz not null default now()
);

-- Auto-populate full-text search column on insert/update
create function documents_tsvector_trigger() returns trigger as $$
begin
  new.fts_tokens := to_tsvector('english', new.content);
  return new;
end
$$ language plpgsql;

create trigger tsvectorupdate before insert or update on documents
for each row execute function documents_tsvector_trigger();

-- Indexes
create index idx_documents_tenant_id on documents(tenant_id);
create index idx_documents_embedding on documents using hnsw (embedding vector_cosine_ops);
create index idx_documents_fts on documents using gin(fts_tokens);

-- Turn on RLS
alter table documents enable row level security;

-- Isolation + role clearance policy.
-- auth.jwt() reads the CALLING USER's token — this only works because the backend
-- queries with the user's own JWT, not the service_role key (see database.py).
create policy tenant_rbac_isolation on documents
for select using (
    tenant_id = ((auth.jwt() -> 'app_metadata') ->> 'tenant_id')::uuid
    and (
        required_role = 'employee'
        or (required_role = 'manager' and (auth.jwt() -> 'app_metadata') ->> 'role' in ('manager','admin'))
        or (required_role = 'admin' and (auth.jwt() -> 'app_metadata') ->> 'role' = 'admin')
    )
);
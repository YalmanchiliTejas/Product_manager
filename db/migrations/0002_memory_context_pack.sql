create extension if not exists vector;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- A1) Incremental ingestion metadata for sources
alter table public.sources
  add column if not exists updated_at timestamptz not null default now(),
  add column if not exists content_hash text,
  add column if not exists last_ingested_at timestamptz;

drop trigger if exists trg_sources_set_updated_at on public.sources;
create trigger trg_sources_set_updated_at
before update on public.sources
for each row
execute function public.set_updated_at();

-- A2) Full-text search support for chunks
alter table public.chunks
  add column if not exists content_tsv tsvector
  generated always as (to_tsvector('english', coalesce(content, ''))) stored;

create index if not exists chunks_content_tsv_gin_idx
  on public.chunks using gin (content_tsv);

-- A3) Memory tables
create table if not exists public.memory_items (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  type text not null,
  title text not null,
  content text not null,
  tags text[] not null default '{}',
  authority int not null default 0,
  effective_from timestamptz not null default now(),
  effective_to timestamptz,
  supersedes_id uuid references public.memory_items(id) on delete set null,
  evidence_chunk_ids uuid[] not null default '{}',
  embedding vector(1536),
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists memory_items_embedding_idx
  on public.memory_items using hnsw (embedding vector_cosine_ops);

create index if not exists memory_items_project_type_idx
  on public.memory_items(project_id, type);

create index if not exists memory_items_effective_idx
  on public.memory_items(project_id, effective_from desc);

drop trigger if exists trg_memory_items_set_updated_at on public.memory_items;
create trigger trg_memory_items_set_updated_at
before update on public.memory_items
for each row
execute function public.set_updated_at();

create table if not exists public.memory_topics (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  name text not null,
  content text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists trg_memory_topics_set_updated_at on public.memory_topics;
create trigger trg_memory_topics_set_updated_at
before update on public.memory_topics
for each row
execute function public.set_updated_at();

create table if not exists public.context_packs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  task_type text not null,
  query text not null,
  packed_json jsonb not null,
  token_estimate int,
  created_at timestamptz not null default now()
);

create table if not exists public.memory_runs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  run_type text not null,
  stats jsonb not null default '{}',
  status text not null default 'ok',
  created_at timestamptz not null default now()
);

-- B1) Keyword search RPC
create or replace function public.keyword_search_chunks(
  input_project_id uuid,
  query text,
  match_count integer default 8
)
returns table (
  chunk_id uuid,
  source_id uuid,
  content text,
  rank double precision
)
language sql
stable
as $$
  select
    c.id as chunk_id,
    c.source_id,
    c.content,
    ts_rank_cd(c.content_tsv, websearch_to_tsquery('english', query)) as rank
  from public.chunks c
  join public.sources s on s.id = c.source_id
  where s.project_id = input_project_id
    and c.content_tsv @@ websearch_to_tsquery('english', query)
  order by rank desc, c.id
  limit greatest(match_count, 1);
$$;

-- B2) Hybrid retrieval RPC
create or replace function public.hybrid_search_chunks(
  input_project_id uuid,
  query text,
  query_embedding vector(1536),
  match_count integer default 8
)
returns table (
  chunk_id uuid,
  source_id uuid,
  content text,
  semantic_score double precision,
  keyword_score double precision,
  combined_score double precision
)
language sql
stable
as $$
  with semantic as (
    select
      s.chunk_id,
      s.source_id,
      s.content,
      s.similarity as semantic_score,
      0::double precision as keyword_score
    from public.semantic_search_chunks(input_project_id, query_embedding, greatest(match_count, 1), null, null) s
  ),
  keyword as (
    select
      k.chunk_id,
      k.source_id,
      k.content,
      0::double precision as semantic_score,
      k.rank as keyword_score
    from public.keyword_search_chunks(input_project_id, query, greatest(match_count, 1)) k
  ),
  unioned as (
    select * from semantic
    union all
    select * from keyword
  ),
  deduped as (
    select
      u.chunk_id,
      max(u.source_id) as source_id,
      max(u.content) as content,
      max(u.semantic_score) as semantic_score,
      max(u.keyword_score) as keyword_score
    from unioned u
    group by u.chunk_id
  )
  select
    d.chunk_id,
    d.source_id,
    d.content,
    d.semantic_score,
    d.keyword_score,
    (0.65 * d.semantic_score + 0.35 * d.keyword_score) as combined_score
  from deduped d
  order by combined_score desc, d.chunk_id
  limit greatest(match_count, 1);
$$;

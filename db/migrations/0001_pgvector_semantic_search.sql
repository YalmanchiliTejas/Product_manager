create extension if not exists vector;

-- Ensure chunks.embedding supports pgvector semantic similarity.
alter table public.chunks
  alter column embedding type vector(1536)
  using embedding::vector;

create index if not exists chunks_embedding_ivfflat_idx
  on public.chunks
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

create or replace function public.semantic_search_chunks(
  input_project_id uuid,
  query_embedding vector(1536),
  match_count integer default 8
)
returns table (
  chunk_id uuid,
  source_id uuid,
  content text,
  metadata jsonb,
  similarity double precision
)
language sql
stable
as $$
  select
    c.id as chunk_id,
    c.source_id,
    c.content,
    c.metadata,
    1 - (c.embedding <=> query_embedding) as similarity
  from public.chunks c
  join public.sources s on s.id = c.source_id
  where s.project_id = input_project_id
    and c.embedding is not null
  order by c.embedding <=> query_embedding
  limit greatest(match_count, 1);
$$;

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
  match_count integer default 8,
  filter_source_types text[] default null,
  filter_segment_tags text[] default null
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
    and (
      filter_source_types is null
      or cardinality(filter_source_types) = 0
      or s.source_type = any(filter_source_types)
    )
    and (
      filter_segment_tags is null
      or cardinality(filter_segment_tags) = 0
      or s.segment_tags && filter_segment_tags
    )
    and c.embedding is not null
  order by c.embedding <=> query_embedding
  limit greatest(match_count, 1);
$$;

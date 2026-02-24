-- Base schema for Beacon
-- Run this before 0001_pgvector_semantic_search.sql

-- Enable required extensions
create extension if not exists "pgcrypto";
create extension if not exists vector;

-- ─────────────────────────────────────────────
-- Projects
-- ─────────────────────────────────────────────
create table if not exists public.projects (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid,                        -- references auth.users(id) when auth is enabled
  name        text not null,
  description text,
  created_at  timestamptz default now(),
  updated_at  timestamptz default now()
);

-- Auto-update updated_at
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger trg_projects_updated_at
  before update on public.projects
  for each row execute function public.set_updated_at();

-- ─────────────────────────────────────────────
-- Sources
-- ─────────────────────────────────────────────
-- raw_content is nullable: a source may be a stored file (file_path) with
-- no inline text, or may have text pasted directly (raw_content).
create table if not exists public.sources (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references public.projects(id) on delete cascade,
  name          text not null,
  source_type   text not null,        -- 'interview' | 'support_ticket' | 'nps' | 'survey' | 'analytics' | 'other'
  segment_tags  text[] default '{}',  -- e.g. ['enterprise', 'churned']
  raw_content   text,                 -- nullable: text may come from a stored file
  file_path     text,                 -- Supabase Storage path if uploaded as a file
  metadata      jsonb default '{}',
  created_at    timestamptz default now()
);

create index if not exists sources_project_id_idx on public.sources(project_id);

-- ─────────────────────────────────────────────
-- Chunks  (text passages for RAG)
-- ─────────────────────────────────────────────
create table if not exists public.chunks (
  id           uuid primary key default gen_random_uuid(),
  source_id    uuid not null references public.sources(id) on delete cascade,
  project_id   uuid not null references public.projects(id) on delete cascade,
  content      text not null,
  chunk_index  integer not null,
  embedding    vector(1536),
  metadata     jsonb default '{}',
  created_at   timestamptz default now()
);

create index if not exists chunks_source_id_idx   on public.chunks(source_id);
create index if not exists chunks_project_id_idx  on public.chunks(project_id);
-- vector index lives in 0001_pgvector_semantic_search.sql

-- ─────────────────────────────────────────────
-- Syntheses  (a snapshot / run of the AI pipeline)
-- NOTE: must come before themes + opportunities due to FK deps
-- ─────────────────────────────────────────────
create table if not exists public.syntheses (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references public.projects(id) on delete cascade,
  trigger_type  text not null,  -- 'manual' | 'auto' | 'chat_query'
  summary       text,
  source_ids    uuid[] not null,
  model_used    text,
  created_at    timestamptz default now()
);

create index if not exists syntheses_project_id_idx on public.syntheses(project_id);

-- ─────────────────────────────────────────────
-- Themes  (AI-extracted recurring patterns)
-- ─────────────────────────────────────────────
create table if not exists public.themes (
  id                   uuid primary key default gen_random_uuid(),
  project_id           uuid not null references public.projects(id) on delete cascade,
  synthesis_id         uuid not null references public.syntheses(id) on delete cascade,
  title                text not null,
  description          text not null,
  frequency_score      float,   -- 0–1: fraction of sources mentioning this
  severity_score       float,   -- 0–1: average severity rating
  segment_distribution jsonb,   -- { "enterprise": 0.8, "smb": 0.3 }
  supporting_quotes    jsonb not null default '[]', -- [{ quote, source_id, chunk_id }]
  created_at           timestamptz default now()
);

create index if not exists themes_synthesis_id_idx on public.themes(synthesis_id);
create index if not exists themes_project_id_idx   on public.themes(project_id);

-- ─────────────────────────────────────────────
-- Opportunities  (prioritised product briefs)
-- ─────────────────────────────────────────────
create table if not exists public.opportunities (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid not null references public.projects(id) on delete cascade,
  synthesis_id      uuid not null references public.syntheses(id) on delete cascade,
  title             text not null,
  problem_statement text not null,
  evidence          jsonb not null default '[]',  -- [{ quote, source_id, theme_id }]
  affected_segments text[] default '{}',
  confidence_score  float,          -- 0–1
  why_now           text,
  ai_reasoning      text,
  rank              integer,
  status            text default 'proposed',  -- 'proposed'|'accepted'|'rejected'|'deferred'
  pm_notes          text,
  created_at        timestamptz default now(),
  updated_at        timestamptz default now()
);

create trigger trg_opportunities_updated_at
  before update on public.opportunities
  for each row execute function public.set_updated_at();

create index if not exists opportunities_synthesis_id_idx on public.opportunities(synthesis_id);
create index if not exists opportunities_project_id_idx   on public.opportunities(project_id);

-- ─────────────────────────────────────────────
-- Conversations
-- ─────────────────────────────────────────────
create table if not exists public.conversations (
  id         uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  title      text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create trigger trg_conversations_updated_at
  before update on public.conversations
  for each row execute function public.set_updated_at();

create index if not exists conversations_project_id_idx on public.conversations(project_id);

-- ─────────────────────────────────────────────
-- Messages
-- ─────────────────────────────────────────────
create table if not exists public.messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  role            text not null,   -- 'user' | 'assistant'
  content         text not null,
  metadata        jsonb default '{}',  -- { cited_sources: [], cited_chunks: [], cited_themes: [] }
  created_at      timestamptz default now()
);

create index if not exists messages_conversation_id_idx on public.messages(conversation_id);

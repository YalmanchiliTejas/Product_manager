-- Knowledge Graph tables — entities, relationships, signal correlations, trend tracking
-- Builds the persistent, evolving intelligence layer on top of existing memory + synthesis

-- 1. Entities — extracted people, products, features, segments mentioned across feedback
CREATE TABLE IF NOT EXISTS public.entities (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    entity_type     text NOT NULL
                    CHECK (entity_type IN ('person','product','feature','segment','company','concept')),
    canonical_name  text NOT NULL,
    aliases         text[] NOT NULL DEFAULT '{}',
    description     text NOT NULL DEFAULT '',
    first_seen_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    mention_count   int NOT NULL DEFAULT 1,
    metadata        jsonb NOT NULL DEFAULT '{}',
    embedding       vector(1536),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS entities_project_type_idx
    ON public.entities(project_id, entity_type);
CREATE INDEX IF NOT EXISTS entities_canonical_name_idx
    ON public.entities(project_id, canonical_name);
CREATE INDEX IF NOT EXISTS entities_embedding_idx
    ON public.entities USING hnsw (embedding vector_cosine_ops);

DROP TRIGGER IF EXISTS trg_entities_set_updated_at ON public.entities;
CREATE TRIGGER trg_entities_set_updated_at
BEFORE UPDATE ON public.entities
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();


-- 2. Entity mentions — links an entity to the specific chunk where it was found
CREATE TABLE IF NOT EXISTS public.entity_mentions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id   uuid NOT NULL REFERENCES public.entities(id) ON DELETE CASCADE,
    chunk_id    uuid NOT NULL REFERENCES public.chunks(id) ON DELETE CASCADE,
    source_id   uuid NOT NULL REFERENCES public.sources(id) ON DELETE CASCADE,
    mention_text text NOT NULL DEFAULT '',
    confidence  double precision NOT NULL DEFAULT 0.8,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS entity_mentions_entity_idx ON public.entity_mentions(entity_id);
CREATE INDEX IF NOT EXISTS entity_mentions_chunk_idx ON public.entity_mentions(chunk_id);
CREATE INDEX IF NOT EXISTS entity_mentions_source_idx ON public.entity_mentions(source_id);


-- 3. Theme relationships — explicit edges between themes that co-occur or relate
CREATE TABLE IF NOT EXISTS public.theme_relationships (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    source_theme_id uuid NOT NULL REFERENCES public.themes(id) ON DELETE CASCADE,
    target_theme_id uuid NOT NULL REFERENCES public.themes(id) ON DELETE CASCADE,
    relationship    text NOT NULL
                    CHECK (relationship IN (
                        'co_occurs',       -- themes appear together in same feedback
                        'depends_on',      -- solving A requires solving B first
                        'contradicts',     -- themes present opposing signals
                        'evolves_into',    -- theme A over time became theme B
                        'amplifies'        -- theme A makes theme B stronger/more urgent
                    )),
    strength        double precision NOT NULL DEFAULT 0.5
                    CHECK (strength >= 0 AND strength <= 1),
    evidence        jsonb NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS theme_rels_project_idx ON public.theme_relationships(project_id);
CREATE INDEX IF NOT EXISTS theme_rels_source_idx ON public.theme_relationships(source_theme_id);
CREATE INDEX IF NOT EXISTS theme_rels_target_idx ON public.theme_relationships(target_theme_id);


-- 4. Signal correlations — cross-theme pattern detection
CREATE TABLE IF NOT EXISTS public.signal_correlations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    correlation_type text NOT NULL
                    CHECK (correlation_type IN (
                        'theme_cooccurrence',   -- two themes mentioned in same session
                        'segment_divergence',   -- segment A says X, segment B says opposite
                        'temporal_spike',       -- theme mentions spiked with an external event
                        'support_correlation',  -- feedback theme correlates with support tickets
                        'feature_gap'           -- users want X but don't use related Y
                    )),
    signal_a        jsonb NOT NULL,   -- {type: "theme"|"entity"|"segment", id: uuid, label: str}
    signal_b        jsonb NOT NULL,   -- {type: "theme"|"entity"|"segment", id: uuid, label: str}
    correlation_score double precision NOT NULL DEFAULT 0.0
                    CHECK (correlation_score >= -1 AND correlation_score <= 1),
    explanation     text NOT NULL DEFAULT '',
    evidence_chunk_ids uuid[] NOT NULL DEFAULT '{}',
    detected_at     timestamptz NOT NULL DEFAULT now(),
    metadata        jsonb NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS signal_corr_project_idx ON public.signal_correlations(project_id);
CREATE INDEX IF NOT EXISTS signal_corr_type_idx ON public.signal_correlations(project_id, correlation_type);


-- 5. Theme trends — tracks how theme strength changes over time across syntheses
CREATE TABLE IF NOT EXISTS public.theme_trends (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    theme_title     text NOT NULL,
    synthesis_id    uuid NOT NULL REFERENCES public.syntheses(id) ON DELETE CASCADE,
    measured_at     timestamptz NOT NULL DEFAULT now(),
    mention_count   int NOT NULL DEFAULT 0,
    segment_spread  int NOT NULL DEFAULT 0,   -- how many distinct segments mention this
    source_count    int NOT NULL DEFAULT 0,   -- how many distinct sources mention this
    severity_avg    double precision NOT NULL DEFAULT 0.0,
    trend_direction text NOT NULL DEFAULT 'stable'
                    CHECK (trend_direction IN ('emerging','accelerating','stable','declining','resurgent')),
    velocity        double precision NOT NULL DEFAULT 0.0,  -- rate of change vs previous
    metadata        jsonb NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS theme_trends_project_idx ON public.theme_trends(project_id, theme_title);
CREATE INDEX IF NOT EXISTS theme_trends_synthesis_idx ON public.theme_trends(synthesis_id);
CREATE INDEX IF NOT EXISTS theme_trends_direction_idx ON public.theme_trends(project_id, trend_direction);


-- 6. Synthesis comparisons — stores diffs between two synthesis runs
CREATE TABLE IF NOT EXISTS public.synthesis_comparisons (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    baseline_synthesis_id uuid NOT NULL REFERENCES public.syntheses(id) ON DELETE CASCADE,
    current_synthesis_id  uuid NOT NULL REFERENCES public.syntheses(id) ON DELETE CASCADE,
    new_themes          jsonb NOT NULL DEFAULT '[]',
    removed_themes      jsonb NOT NULL DEFAULT '[]',
    accelerating_themes jsonb NOT NULL DEFAULT '[]',
    declining_themes    jsonb NOT NULL DEFAULT '[]',
    stable_themes       jsonb NOT NULL DEFAULT '[]',
    contradictions      jsonb NOT NULL DEFAULT '[]',
    summary             text NOT NULL DEFAULT '',
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS synth_comp_project_idx ON public.synthesis_comparisons(project_id);


-- 7. Snapshot comparisons — stores diffs between two memory snapshots
CREATE TABLE IF NOT EXISTS public.snapshot_comparisons (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    baseline_snapshot_id uuid NOT NULL REFERENCES public.memory_items(id) ON DELETE CASCADE,
    current_snapshot_id  uuid NOT NULL REFERENCES public.memory_items(id) ON DELETE CASCADE,
    new_items           jsonb NOT NULL DEFAULT '[]',
    removed_items       jsonb NOT NULL DEFAULT '[]',
    changed_items       jsonb NOT NULL DEFAULT '[]',
    summary             text NOT NULL DEFAULT '',
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS snap_comp_project_idx ON public.snapshot_comparisons(project_id);

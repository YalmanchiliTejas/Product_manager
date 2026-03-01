-- Interview Agent tables
-- interview_sessions, interview_tasks, prd_documents, tickets

-- 1. Interview sessions — tracks each orchestrator run
CREATE TABLE IF NOT EXISTS interview_sessions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id     text NOT NULL,
    status      text NOT NULL DEFAULT 'intake'
                CHECK (status IN ('intake','waiting','planning','researching','generating','ticketing','complete')),
    interview_data  jsonb DEFAULT '[]'::jsonb,
    market_context  text DEFAULT '',
    current_question text DEFAULT '',
    research_results jsonb DEFAULT '{}'::jsonb,
    context_pack    jsonb DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_interview_sessions_project ON interview_sessions(project_id);
CREATE INDEX idx_interview_sessions_user    ON interview_sessions(user_id);

-- 2. Interview tasks — shared task list (user-confirmable)
CREATE TABLE IF NOT EXISTS interview_tasks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  uuid NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
    title       text NOT NULL,
    description text DEFAULT '',
    status      text NOT NULL DEFAULT 'proposed'
                CHECK (status IN ('proposed','confirmed','in_progress','completed','rejected')),
    priority    int NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    agent       text NOT NULL DEFAULT 'orchestrator'
                CHECK (agent IN ('orchestrator','research','context','prd','ticket')),
    output      jsonb DEFAULT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_interview_tasks_session ON interview_tasks(session_id);

-- 3. PRD documents — generated PRDs
CREATE TABLE IF NOT EXISTS prd_documents (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        uuid NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
    project_id        uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title             text NOT NULL,
    content           text NOT NULL DEFAULT '',
    kpis              jsonb DEFAULT '[]'::jsonb,
    next_actions      jsonb DEFAULT '[]'::jsonb,
    cited_chunk_ids   uuid[] DEFAULT '{}',
    cited_memory_ids  uuid[] DEFAULT '{}',
    validation_status text NOT NULL DEFAULT 'draft'
                      CHECK (validation_status IN ('draft','validated','approved')),
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_prd_documents_session ON prd_documents(session_id);
CREATE INDEX idx_prd_documents_project ON prd_documents(project_id);

-- 4. Tickets — implementation tickets from PRD
CREATE TABLE IF NOT EXISTS tickets (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    prd_id              uuid NOT NULL REFERENCES prd_documents(id) ON DELETE CASCADE,
    session_id          uuid NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
    project_id          uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    ticket_type         text NOT NULL DEFAULT 'task'
                        CHECK (ticket_type IN ('epic','story','task','bug')),
    title               text NOT NULL,
    description         text NOT NULL DEFAULT '',
    acceptance_criteria jsonb DEFAULT '[]'::jsonb,
    priority            text NOT NULL DEFAULT 'medium'
                        CHECK (priority IN ('critical','high','medium','low')),
    estimated_points    int DEFAULT NULL,
    parent_ticket_id    uuid DEFAULT NULL REFERENCES tickets(id) ON DELETE SET NULL,
    labels              text[] DEFAULT '{}',
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_tickets_prd     ON tickets(prd_id);
CREATE INDEX idx_tickets_session ON tickets(session_id);
CREATE INDEX idx_tickets_parent  ON tickets(parent_ticket_id);

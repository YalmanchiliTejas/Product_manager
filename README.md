Product Plan: Beacon — The AI Product Discovery Engine
"Cursor for Product Managers"
Working name: Beacon — because it illuminates what to build next. Alternative names to consider: Signal, Thread, Prism, Loop


Table of Contents
Executive Summary
Problem & Opportunity
Product Strategy
MVP Scope (Phase 1)
Technical Architecture
Data Model
AI Pipeline Design
Development Phases & Milestones
Go-to-Market Strategy
Pricing & Revenue Model
YC Application Strategy
Risk Mitigation
Success Metrics
Team & Execution


1. Executive Summary
What we're building: An AI-native product discovery system that takes raw customer signals (interviews, support tickets, usage data) and produces prioritized, evidence-backed product opportunities with implementation-ready specs — all through a conversational interface.

Why now:

AI coding agents (Cursor, Claude Code) have solved "how to build" but created a bottleneck at "what to build"
The output of product discovery needs to evolve from human-readable docs to agent-consumable instruction sets
No existing tool closes the full loop from customer signal → coding-agent-ready task
YC has explicitly called this out as a high-priority opportunity (RFS Feb 2026)

The wedge: Start with interview/feedback synthesis → opportunity briefs (steps 1-3 of the full loop). This alone is enormously valuable and shippable fast.

Target outcome: Working MVP in 3-4 weeks, first paying users within 8 weeks, YC application with traction data.


2. Problem & Opportunity
The Problem (in the PM's words)
"I just did 15 customer interviews. I have 200 support tickets from last month. I have Mixpanel data showing drop-off. I know there are patterns here, but it takes me a week to synthesize this into something actionable — and by then, the sprint has already started with whatever we guessed was important."
The Gap in the Market
Stage
Current Tools
Gap
Collect feedback
Dovetail, Gong, Intercom
Great at collection, weak at cross-source synthesis
Synthesize insights
Dovetail AI, BuildBetter
Themes stay trapped in the tool, don't flow downstream
Prioritize opportunities
Productboard, Airfocus
Scoring frameworks require manual input, no AI reasoning
Write specs
Google Docs, Notion AI
Disconnected from evidence, starts from blank page
Create dev tasks
Jira, Linear
No link back to why we're building this
Hand off to coding agents
(nothing)
Complete white space


Our insight: These aren't separate problems. They're one workflow that's been artificially fragmented across 6 tools. We unify it.


3. Product Strategy
3.1 Wedge → Platform Expansion
PHASE 1 (MVP - Weeks 1-4):     Ingest → Synthesize → Opportunity Briefs

PHASE 2 (Weeks 5-10):          + Solution Sketching + Spec Generation

PHASE 3 (Weeks 11-16):         + Coding Agent Export + Integrations

PHASE 4 (Post-funding):        + Longitudinal Memory + Multi-user + Analytics Ingestion
3.2 Primary UX Paradigm: Conversational + Structured
The interface is a chat-first workspace, not a dashboard with a chatbot bolted on.

Left panel: Project sources (uploaded files, imported data)
Center panel: Conversational AI interface (the primary interaction)
Right panel: Structured outputs (opportunity board, specs, evidence trail)

This mirrors the Cursor paradigm: the AI conversation IS the workspace, with structured artifacts generated alongside.
3.3 Core Design Principles
Evidence-threaded: Every output links to source material. Always.
Opinionated AI: The system challenges assumptions, doesn't just summarize
Human-in-the-loop: AI proposes, PM approves/edits at every stage
Export-first: Every artifact is exportable (Markdown, JSON, clipboard)
Session memory: Conversations and insights persist and compound


4. MVP Scope (Phase 1)
What's IN the MVP (3-4 week build)
4.1 Signal Ingestion
Text upload: Drag-and-drop .txt, .md, .csv, .json files
Paste input: Quick-paste interview notes, support tickets, NPS verbatims
Bulk upload: Upload multiple files at once (e.g., a folder of interview transcripts)
Source tagging: Label sources by type (interview, support ticket, NPS, survey) and segment (enterprise, SMB, free user)
4.2 AI Synthesis Engine
Theme clustering: Automatically identify recurring pain points, feature requests, and behavioral patterns across all sources
Quote extraction: Pull exact quotes that support each theme, with attribution to source
Frequency + segment scoring: "Mentioned by 8/12 enterprise users" — not just "users want this"
Contradiction detection: Flag where stated needs conflict with each other or with usage patterns
Synthesis summary: Natural language summary of key findings
4.3 Opportunity Briefs
Prioritized opportunity list: Ranked by AI with reasoning visible
Each opportunity includes:
Problem statement
Supporting evidence (linked quotes + data)
Affected user segments
AI confidence score
"Why now?" reasoning
PM can: edit, reorder, dismiss, or ask follow-up questions about any opportunity
4.4 Conversational Interface
Chat with your data: "What are enterprise users struggling with?" / "What should we build next?" / "Compare feedback from Q4 vs Q1"
Follow-up questions: Drill into any theme or opportunity conversationally
Challenge mode: "Play devil's advocate on this opportunity" / "What are we missing?"
Session history: All conversations saved and searchable
4.5 Export
Opportunity briefs as Markdown
Copy to clipboard (formatted for Notion, Google Docs, Slack)
Raw JSON export for programmatic use

4.6 Context and Knowledge graphs:
Build longitudinal memory and context to make proper correlations and knowledge to come up with PRDS
What's OUT of MVP
Audio/video transcription (users pre-transcribe or use Otter/Gong)
Live integrations (Jira, Slack, Intercom, etc.)
Multi-user / collaboration
Solution sketching / UI proposals
Spec & ticket generation
Analytics data ingestion (Mixpanel, Amplitude)
Figma integration
Roadmap views


5. Technical Architecture
5.1 Stack Decision
Layer
Technology
Rationale
Frontend
Next.js 14+ (App Router)
Fast SSR, great DX, easy Vercel deploy
UI Components
Tailwind CSS + shadcn/ui
Rapid, professional UI without design overhead
Backend
Next.js API Routes + Server Actions
Unified codebase, less infra to manage
Database
PostgreSQL via Supabase
Auth, DB, storage, realtime, vector search (pgvector) all-in-one
AI
Anthropic Claude API (claude-sonnet-4-6 for speed, claude-opus-4-6 for deep analysis)
Best reasoning for synthesis tasks, structured output support
Embeddings
Voyage AI or OpenAI embeddings
For RAG pipeline (semantic search over source material)
File Storage
Supabase Storage (S3-compatible)
Store uploaded transcripts and documents
Deployment
Vercel
Zero-config, instant deploys, edge functions
Auth
Supabase Auth
Email/password + OAuth (Google) out of the box
Payments
Stripe
Industry standard, fast to integrate

5.2 System Architecture
┌─────────────────────────────────────────────────────────┐

│                    FRONTEND (Next.js)                    │

│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │

│  │  Source   │  │    Chat      │  │   Opportunity     │  │

│  │  Panel    │  │  Interface   │  │   Board / Output  │  │

│  └────┬─────┘  └──────┬───────┘  └────────┬──────────┘  │

│       │               │                    │             │

└───────┼───────────────┼────────────────────┼─────────────┘

       │               │                    │

┌───────┼───────────────┼────────────────────┼─────────────┐

│       ▼               ▼                    ▼             │

│              BACKEND (Next.js API Routes)                │

│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │

│  │   Ingestion   │  │  AI Pipeline │  │   Export     │   │

│  │   Service     │  │  Orchestrator│  │   Service    │   │

│  └──────┬───────┘  └──────┬───────┘  └──────────────┘   │

│         │                 │                              │

│  ┌──────▼───────┐  ┌──────▼───────┐                     │

│  │  Chunking +  │  │  Claude API  │                     │

│  │  Embedding   │  │  (Synthesis) │                     │

│  └──────┬───────┘  └──────┬───────┘                     │

│         │                 │                              │

└─────────┼─────────────────┼──────────────────────────────┘

         │                 │

┌─────────▼─────────────────▼──────────────────────────────┐

│                    SUPABASE                               │

│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐  │

│  │   Auth   │  │ Postgres │  │ pgvector │  │ Storage │  │

│  │          │  │ (data)   │  │ (embeds) │  │ (files) │  │

│  └──────────┘  └──────────┘  └──────────┘  └─────────┘  │

└──────────────────────────────────────────────────────────┘
5.3 AI Pipeline Architecture (Critical Path)
The AI pipeline is the core IP. Here's how it works:

Step 1: INGESTION

 Upload file → Extract text → Clean/normalize → Chunk into passages

 Each chunk: { text, source_file, source_type, segment_tags, position }

 

Step 2: EMBEDDING

 Each chunk → Embedding model → Store vector in pgvector

 This enables semantic search across ALL uploaded material

 

Step 3: SYNTHESIS (triggered by user query or on-demand)

 User asks "What should we build next?"

 │

 ├─ Retrieve relevant chunks via semantic search (top-k)

 ├─ Also retrieve ALL chunks grouped by source for full-context analysis

 │

 ├─ PASS 1: Theme Extraction (Claude Sonnet — fast)

 │   "Given these customer interviews, identify the top recurring themes.

 │    For each theme, extract exact supporting quotes with attribution."

 │

 ├─ PASS 2: Opportunity Scoring (Claude Opus — deep reasoning)

 │   "Given these themes, rank them as product opportunities.

 │    Consider: frequency, severity, segment distribution, feasibility.

 │    Flag contradictions between stated needs and behavioral data.

 │    Provide reasoning for each ranking."

 │

 ├─ PASS 3: Opportunity Brief Generation (Claude Sonnet)

 │   For each top opportunity, generate a structured brief:

 │   { problem, evidence[], affected_segments, confidence, why_now }

 │

 └─ Return structured response to user with citations

 

Step 4: CONVERSATIONAL FOLLOW-UP

 User asks "Tell me more about theme #3"

 │

 ├─ Retrieve theme context + original chunks via embedding search

 ├─ Generate detailed response with quotes and reasoning

 └─ User can edit, challenge, or drill deeper


6. Data Model
Core Entities
-- A workspace/company using Beacon

CREATE TABLE projects (

 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

 user_id UUID REFERENCES auth.users(id),

 name TEXT NOT NULL,

 description TEXT,

 created_at TIMESTAMPTZ DEFAULT now(),

 updated_at TIMESTAMPTZ DEFAULT now()

);

 

-- An uploaded source document

CREATE TABLE sources (

 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

 project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

 name TEXT NOT NULL,

 source_type TEXT NOT NULL, -- 'interview', 'support_ticket', 'nps', 'survey', 'analytics', 'other'

 segment_tags TEXT[] DEFAULT '{}', -- e.g., ['enterprise', 'churned']

 raw_content TEXT NOT NULL,

 file_path TEXT, -- Supabase storage path if uploaded as file

 metadata JSONB DEFAULT '{}',

 created_at TIMESTAMPTZ DEFAULT now()

);

 

-- Chunked passages from sources (for RAG)

CREATE TABLE chunks (

 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

 source_id UUID REFERENCES sources(id) ON DELETE CASCADE,

 project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

 content TEXT NOT NULL,

 chunk_index INTEGER NOT NULL,

 embedding VECTOR(1536), -- pgvector

 metadata JSONB DEFAULT '{}',

 created_at TIMESTAMPTZ DEFAULT now()

);

 

-- AI-generated themes from synthesis

CREATE TABLE themes (

 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

 project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

 synthesis_id UUID REFERENCES syntheses(id) ON DELETE CASCADE,

 title TEXT NOT NULL,

 description TEXT NOT NULL,

 frequency_score FLOAT, -- 0-1, how often mentioned

 severity_score FLOAT, -- 0-1, how painful

 segment_distribution JSONB, -- { "enterprise": 0.8, "smb": 0.3 }

 supporting_quotes JSONB NOT NULL, -- [{ quote, source_id, chunk_id }]

 created_at TIMESTAMPTZ DEFAULT now()

);

 

-- AI-generated opportunity briefs

CREATE TABLE opportunities (

 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

 project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

 synthesis_id UUID REFERENCES syntheses(id) ON DELETE CASCADE,

 title TEXT NOT NULL,

 problem_statement TEXT NOT NULL,

 evidence JSONB NOT NULL, -- [{ quote, source_id, theme_id }]

 affected_segments TEXT[] DEFAULT '{}',

 confidence_score FLOAT, -- 0-1

 why_now TEXT,

 ai_reasoning TEXT, -- Why the AI ranked this here

 rank INTEGER,

 status TEXT DEFAULT 'proposed', -- 'proposed', 'accepted', 'rejected', 'deferred'

 pm_notes TEXT, -- PM's annotations

 created_at TIMESTAMPTZ DEFAULT now(),

 updated_at TIMESTAMPTZ DEFAULT now()

);

 

-- A synthesis run (snapshot of an analysis)

CREATE TABLE syntheses (

 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

 project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

 trigger_type TEXT NOT NULL, -- 'manual', 'auto', 'chat_query'

 summary TEXT,

 source_ids UUID[] NOT NULL, -- Which sources were analyzed

 model_used TEXT,

 created_at TIMESTAMPTZ DEFAULT now()

);

 

-- Chat conversations

CREATE TABLE conversations (

 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

 project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

 title TEXT,

 created_at TIMESTAMPTZ DEFAULT now(),

 updated_at TIMESTAMPTZ DEFAULT now()

);

 

-- Individual messages in a conversation

CREATE TABLE messages (

 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

 conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,

 role TEXT NOT NULL, -- 'user', 'assistant'

 content TEXT NOT NULL,

 metadata JSONB DEFAULT '{}', -- { cited_sources: [], cited_themes: [] }

 created_at TIMESTAMPTZ DEFAULT now()

);

 

-- Create vector similarity search index

CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);


7. AI Pipeline Design — Detailed Prompting Strategy
7.1 Theme Extraction Prompt (Pass 1)
You are an expert product researcher analyzing customer feedback for a product team.

 

CONTEXT:

You are analyzing {n} sources for the product "{project_name}": {project_description}

 

SOURCES:

{formatted_source_chunks}

 

TASK:

Identify the top recurring themes across these sources. For each theme:

 

1. **Title**: A concise, actionable name (e.g., "Search performance frustration" not "Search")

2. **Description**: 2-3 sentences explaining the theme

3. **Frequency**: How many distinct sources mention this theme (with count)

4. **Severity**: How painful is this for users (low/medium/high/critical) based on language intensity

5. **Supporting Quotes**: Extract 2-5 EXACT quotes from the sources that support this theme.

  For each quote, include the source identifier.

6. **Segments**: Which user segments are affected (if segment tags are available)

 

IMPORTANT:

- Only extract themes that appear in 2+ sources (unless a single source describes extreme severity)

- Use exact quotes — never paraphrase

- If sources contradict each other, flag this explicitly

- Distinguish between what users SAY they want vs. what the data SUGGESTS they need

 

Return as structured JSON.
7.2 Opportunity Scoring Prompt (Pass 2)
You are a senior product strategist. Given the following themes extracted from customer research,

your job is to frame them as PRODUCT OPPORTUNITIES and rank them.

 

THEMES:

{themes_json}

 

For each opportunity:

1. **Problem Statement**: Frame the theme as a problem worth solving (1-2 sentences)

2. **Evidence Strength**: How much evidence supports this? (strong/moderate/weak)

3. **Segment Impact**: Which segments care most? What's the revenue/retention implication?

4. **Confidence Score**: 0-1, how confident you are this is a real opportunity

5. **Why Now**: Why is this the right time to address this?

6. **Risks/Counterarguments**: Why might this NOT be worth building?

7. **Rank**: Overall priority rank with reasoning

 

RANKING CRITERIA (in order of importance):

- Frequency × Severity (how many people, how badly)

- Segment value (enterprise pain > free-tier pain, unless retention-critical)

- Evidence quality (direct quotes > inferred needs)

- Feasibility signal (is the solution space constrained or wide open?)

 

CRITICAL INSTRUCTION:

Do NOT just summarize what users said. Actively reason about:

- Are users describing symptoms or root causes?

- Would solving this actually change behavior, or is it a "nice to have"?

- Are there non-obvious connections between themes?

 

Be opinionated. PMs need a partner who challenges them, not a yes-machine.

 

Return as structured JSON.
7.3 Conversational Response Prompt
You are Beacon, an AI product discovery assistant. You help PMs figure out what to build

by synthesizing customer feedback and usage data.

 

PROJECT CONTEXT:

{project_name}: {project_description}

 

AVAILABLE KNOWLEDGE:

{relevant_themes_and_opportunities}

 

RELEVANT SOURCE MATERIAL:

{retrieved_chunks_via_rag}

 

CONVERSATION HISTORY:

{previous_messages}

 

USER QUERY: {user_message}

 

RESPONSE GUIDELINES:

- Ground every claim in evidence. Cite specific sources and quotes.

- Be direct and opinionated. Don't hedge when the data is clear.

- If the PM's assumption contradicts the data, say so respectfully but clearly.

- If you don't have enough data to answer confidently, say so and suggest what additional

 data would help.

- Use structured formatting (headers, bullets, tables) when it aids clarity.

- If the user asks "what should we build next?", reference the opportunity ranking and explain

 your reasoning.


8. Development Phases & Milestones
Phase 1: MVP Core (Weeks 1-4)
Week 1: Foundation

Project scaffolding (Next.js + Supabase + Tailwind + shadcn/ui)
Auth flow (sign up, sign in, sign out)
Database schema creation (all tables above)
Project CRUD (create, list, select project)
Basic layout shell (three-panel: sources | chat | outputs)

Week 2: Ingestion + Embedding Pipeline

File upload UI (drag-and-drop, multi-file)
Text paste input UI
Source management (list, delete, tag sources with type + segment)
Backend: file processing pipeline (extract text, chunk, embed, store)
Backend: pgvector setup and semantic search function

Week 3: AI Synthesis + Chat

Chat interface UI (message list, input, streaming responses)
Backend: RAG pipeline (query → embed → retrieve → augment → generate)
Backend: Theme extraction pipeline (Pass 1)
Backend: Opportunity scoring pipeline (Pass 2)
"Synthesize" button that runs full analysis on all project sources
Display themes and opportunities in the output panel

Week 4: Polish + Evidence Trail + Export

Click-through evidence trail (opportunity → quotes → source)
Opportunity board UI (reorder, accept/reject/defer, add notes)
Export: Markdown download, copy-to-clipboard
Session/conversation history (list past chats, resume)
Loading states, error handling, empty states
Landing page (simple, compelling — explain the value prop)

Milestone: Deployable MVP on a public URL. Can demo the full wedge loop.
Phase 2: Depth + Spec Generation (Weeks 5-10)
Solution sketching: AI proposes UI changes, data model changes, workflows
PRD generation from opportunities
Task breakdown: Decompose PRD into dev-ready tasks
Coding agent export format (structured prompts for Claude Code / Cursor)
Improved synthesis: multi-pass, cross-session learning
Source type: CSV upload with column mapping (for analytics/NPS data)
Contradiction detection improvements
User onboarding flow / tutorial
Phase 3: Integrations + Growth (Weeks 11-16)
Slack integration (pull feedback from channels)
Jira/Linear integration (push tasks)
Intercom/Zendesk integration (pull support tickets)
Multi-user: team workspace, shared projects
Billing: Stripe integration, usage-based pricing
API for programmatic access
Phase 4: Moat-Building (Post-Funding)
Longitudinal product memory (cross-session, cross-quarter analysis)
Analytics ingestion (Mixpanel, Amplitude connectors)
Audio/video transcription (built-in Whisper or Deepgram)
Figma plugin (push UI sketches)
Competitive intelligence overlay
Enterprise features (SSO, audit logs, roles/permissions)


9. Go-to-Market Strategy
9.1 Target Users (in priority order)
Primary: Startup founders (2-50 person companies)

Do their own PM work, drowning in customer feedback
Already using AI tools (Cursor, Claude), understand the paradigm
Fast decision-makers, can adopt immediately
Found on: Twitter/X, Hacker News, YC community, Product Hunt, Indie Hackers

Secondary: Product Managers at growth-stage companies (50-500)

Formal PM process, need to justify decisions with evidence
Currently spending days on synthesis that Beacon does in minutes
Higher willingness to pay, longer sales cycle
Found on: Lenny's Newsletter, Mind the Product, LinkedIn, PM communities

Tertiary: Engineering teams without dedicated PMs

Engineers forced into PM role, want to minimize time spent on it
Value structured output that feeds directly into their workflow
Found on: Hacker News, Dev.to, GitHub, Reddit r/programming
9.2 Launch Sequence
Pre-launch (during build — Weeks 1-4):

Build in public on Twitter/X — show the AI synthesis in action
Post "building this because YC said someone should" on HN/Twitter
Collect waitlist emails via a simple landing page
Record 2-3 short demo videos (< 60 seconds each)

Soft launch (Week 5):

Invite 10-20 waitlist users for private beta
Do 1:1 onboarding calls with each (this IS your customer research)
Iterate rapidly based on feedback

Public launch (Week 8-10):

Product Hunt launch
Hacker News Show HN post
Cross-post on Indie Hackers, Reddit r/ProductManagement, LinkedIn
Lenny's Newsletter mention (pitch the author directly)

Ongoing growth:

Content marketing: "How we analyzed 50 customer interviews in 10 minutes"
SEO: target "AI product management", "customer interview analysis tool", "what to build next"
Twitter/X: Share anonymized examples of insights generated
Community: Host "PM office hours" where you demo Beacon on participants' real data
9.3 Viral/Growth Mechanics Built Into Product
Shareable insight reports: PMs share Beacon-generated briefs with their team → team sees the tool
"Powered by Beacon" watermark on free-tier exports
Template gallery: Pre-built analysis templates that attract organic search traffic


10. Pricing & Revenue Model
Recommended Model: Usage-Based with Tiers
Tier
Price
Includes
Target
Free
$0/mo
1 project, 5 sources, 10 chat messages/mo
Trial / Solo hackers
Pro
$49/mo
5 projects, unlimited sources, unlimited chat, full export
Startup founders
Team
$29/user/mo (min 3)
Shared workspace, collaboration, priority support
Growth-stage PM teams
Enterprise
Custom
SSO, audit logs, custom integrations, dedicated support
Large companies


Why this model:

Free tier drives adoption and word-of-mouth
$49/mo is an easy expense for any funded startup (no procurement needed)
Team tier creates multi-seat expansion revenue
Usage limits on free tier create natural upgrade pressure

Revenue targets:

Month 1-2: 0 revenue (free beta)
Month 3: $500/mo (10 Pro users)
Month 6: $5,000/mo (100 Pro users or mix of Pro + Team)
Month 12: $25,000/mo (500 users, mix of tiers) — this is strong YC demo day traction


11. YC Application Strategy
11.1 Timing
YC S26 applications likely open March-April 2026
Ideal: apply with a working product + early traction data
Even 10-20 active users who love it is enough
11.2 What YC Wants to See
Founders who understand the problem deeply — Can you articulate why existing tools fail?
A working product — Not a pitch deck. A demo.
Early signal of demand — Waitlist signups, beta user engagement, willingness to pay
Speed of execution — How fast did you go from idea to product?
Market insight — Why now? Why is this a $1B+ opportunity?
11.3 YC Application Narrative
One-liner: "Beacon is the AI-native product discovery engine — Cursor for PMs. Upload customer interviews, ask 'what should we build next?', get evidence-backed opportunities with coding-agent-ready specs."

Key talking points for interview:

"The output of product management needs to change. PRDs were designed for human engineers. Coding agents need structured instruction sets grounded in customer evidence."
"Every tool in this space stops at synthesis. We're the first to close the loop from customer quote → dev task."
"We built a working product in [X] weeks. Here's a demo with real data."
"We have [N] beta users. Here's what they told us." (Use Beacon to analyze your own user feedback — meta-demo)
11.4 The Meta Play
Use Beacon to build Beacon. Upload your own customer interviews as source material. Show YC that you used your own product to decide what features to prioritize. This is the most powerful demo possible.


12. Risk Mitigation
Risk
Likelihood
Impact
Mitigation
AI hallucination / wrong insights
Medium
High
Strict grounding: every claim must link to source quote. Confidence scores. "I don't have enough data" responses.
Competitors ship similar product
High
Medium
Speed to market. Build longitudinal memory moat early. Focus on evidence-threading as differentiator.
PMs don't trust AI for strategic decisions
Medium
High
Start with synthesis (low-risk, high-value). Build trust progressively. Always keep human-in-the-loop.
Claude API costs too high at scale
Low
Medium
Use Sonnet for fast tasks, Opus only for deep analysis. Cache common patterns. Optimize chunk retrieval.
Users don't have enough data to get value
Medium
Medium
Provide sample data / templates. Beacon works with as few as 3-5 interview transcripts.
Supabase limitations at scale
Low
Low
Architecture allows migration to self-hosted Postgres + custom auth if needed.



13. Success Metrics
MVP Launch (Week 4)
Fully functional ingestion → synthesis → opportunity pipeline
3+ people outside the founding team have used it
Average synthesis quality rated 4+/5 by test users
Month 2
50+ waitlist signups
20+ active beta users
NPS > 40 from beta cohort
3+ unsolicited "this is amazing" messages
Month 3 (Pre-YC Application)
$500+ MRR (or strong free → paid conversion signal)
100+ registered users
At least 1 user who would be "very disappointed" if Beacon went away
Clear evidence of the "aha moment" in user journey
Month 6
$5,000+ MRR
500+ users
1+ integration live (Slack or Jira)
Longitudinal memory feature working


14. Team & Execution
Recommended Role Split (2 founders)
Founder A: Product + Growth

User research, landing page, content marketing
Onboarding calls with beta users
YC application narrative
Community building (Twitter, HN, PM communities)

Founder B: Engineering

Frontend + backend development
AI pipeline (prompting, RAG, quality iteration)
Infrastructure and deployment
Data model and performance

Both founders:

Test the product on real data constantly
Do customer interviews weekly (and feed them into Beacon!)
Decide product priorities together
Key Principle: Ship daily, talk to users weekly.
The fastest way to fail is to build in silence for months. The fastest way to succeed is to get real feedback every week and ship improvements every day.


Appendix A: File & Folder Structure (Next.js)
beacon/

├── src/

│   ├── app/                          # Next.js App Router

│   │   ├── (auth)/                   # Auth routes (sign-in, sign-up)

│   │   │   ├── sign-in/page.tsx

│   │   │   └── sign-up/page.tsx

│   │   ├── (dashboard)/              # Authenticated routes

│   │   │   ├── layout.tsx            # Dashboard layout (sidebar)

│   │   │   ├── projects/

│   │   │   │   ├── page.tsx          # Project list

│   │   │   │   └── [id]/

│   │   │   │       ├── page.tsx      # Project workspace (main 3-panel view)

│   │   │   │       ├── sources/

│   │   │   │       │   └── page.tsx  # Source management

│   │   │   │       └── opportunities/

│   │   │   │           └── page.tsx  # Opportunity board

│   │   │   └── settings/

│   │   │       └── page.tsx

│   │   ├── api/                      # API routes

│   │   │   ├── sources/

│   │   │   │   ├── route.ts          # CRUD sources

│   │   │   │   └── upload/route.ts   # File upload handler

│   │   │   ├── synthesis/

│   │   │   │   ├── route.ts          # Trigger synthesis

│   │   │   │   └── stream/route.ts   # Streaming synthesis

│   │   │   ├── chat/

│   │   │   │   └── route.ts          # Chat endpoint (streaming)

│   │   │   ├── opportunities/

│   │   │   │   └── route.ts          # CRUD opportunities

│   │   │   └── export/

│   │   │       └── route.ts          # Export handler

│   │   ├── layout.tsx                # Root layout

│   │   └── page.tsx                  # Landing page

│   ├── components/

│   │   ├── ui/                       # shadcn/ui components

│   │   ├── chat/

│   │   │   ├── ChatInterface.tsx     # Main chat component

│   │   │   ├── MessageList.tsx

│   │   │   ├── MessageBubble.tsx

│   │   │   └── ChatInput.tsx

│   │   ├── sources/

│   │   │   ├── SourceUploader.tsx    # Drag-and-drop upload

│   │   │   ├── SourceList.tsx

│   │   │   ├── SourceCard.tsx

│   │   │   └── TextPasteInput.tsx

│   │   ├── opportunities/

│   │   │   ├── OpportunityBoard.tsx  # Kanban-style board

│   │   │   ├── OpportunityCard.tsx

│   │   │   └── EvidenceTrail.tsx     # Click-through to source quotes

│   │   ├── synthesis/

│   │   │   ├── ThemeList.tsx

│   │   │   ├── ThemeCard.tsx

│   │   │   └── SynthesisSummary.tsx

│   │   └── layout/

│   │       ├── Sidebar.tsx

│   │       ├── ThreePanel.tsx

│   │       └── TopNav.tsx

│   ├── lib/

│   │   ├── supabase/

│   │   │   ├── client.ts             # Browser Supabase client

│   │   │   ├── server.ts             # Server Supabase client

│   │   │   └── middleware.ts         # Auth middleware

│   │   ├── ai/

│   │   │   ├── claude.ts             # Claude API wrapper

│   │   │   ├── embeddings.ts         # Embedding generation

│   │   │   ├── rag.ts                # RAG pipeline

│   │   │   ├── synthesis.ts          # Theme extraction + opportunity scoring

│   │   │   └── prompts.ts            # All prompt templates

│   │   ├── ingestion/

│   │   │   ├── chunker.ts            # Text chunking logic

│   │   │   ├── parser.ts             # File parsing (txt, csv, json, md)

│   │   │   └── embedder.ts           # Chunk → embedding → store

│   │   └── utils/

│   │       ├── export.ts             # Markdown/JSON export

│   │       └── formatting.ts

│   └── types/

│       └── index.ts                  # TypeScript types

├── supabase/

│   └── migrations/                   # Database migrations

│       └── 001_initial_schema.sql

├── public/

├── .env.local                        # Environment variables

├── next.config.js

├── tailwind.config.ts

├── tsconfig.json

├── package.json

└── PRODUCT_PLAN.md                   # This file


Appendix B: Environment Variables
# Supabase

NEXT_PUBLIC_SUPABASE_URL=your-project-url

NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key

SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

 

# Anthropic

ANTHROPIC_API_KEY=your-api-key

 

# Embeddings (choose one)

OPENAI_API_KEY=your-openai-key          # For OpenAI embeddings

# or

VOYAGE_API_KEY=your-voyage-key          # For Voyage AI embeddings

 

# Stripe (Phase 3)

STRIPE_SECRET_KEY=your-stripe-key

STRIPE_WEBHOOK_SECRET=your-webhook-secret

NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=your-publishable-key

 

# App

NEXT_PUBLIC_APP_URL=http://localhost:3000


Appendix C: Quick-Start Commands
# Create the project

npx create-next-app@latest beacon --typescript --tailwind --eslint --app --src-dir

 

# Install core dependencies

cd beacon

npm install @supabase/supabase-js @supabase/ssr @anthropic-ai/sdk

npm install ai                    # Vercel AI SDK for streaming

 

# Install UI dependencies

npx shadcn@latest init

npx shadcn@latest add button card input textarea dialog dropdown-menu

npx shadcn@latest add tabs badge scroll-area separator avatar

npx shadcn@latest add toast sheet command popover

 

# Install utility dependencies

npm install lucide-react           # Icons

npm install react-dropzone         # File upload

npm install react-markdown         # Markdown rendering

npm install date-fns               # Date formatting

npm install zod                    # Schema validation

npm install uuid                   # UUID generation

 

# Dev tools

npm install -D @types/uuid



This plan is a living document. Update it as you learn from users and iterate on the product.


import { redirect, notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { ThreePanel } from "@/components/layout/ThreePanel";
import { SourcesPanel } from "./SourcesPanel";
import { ChatPanel } from "./ChatPanel";
import { OutputsPanel } from "./OutputsPanel";

async function getProject(id: string, userId: string) {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("projects")
    .select("*")
    .eq("id", id)
    .eq("user_id", userId)
    .single();

  if (error || !data) return null;
  return data;
}

async function getSources(projectId: string) {
  const supabase = await createClient();
  const { data } = await supabase
    .from("sources")
    .select("id, name, source_type, segment_tags, created_at")
    .eq("project_id", projectId)
    .order("created_at", { ascending: false });
  return data ?? [];
}

interface ProjectPageProps {
  params: Promise<{ id: string }>;
}

export default async function ProjectPage({ params }: ProjectPageProps) {
  const { id } = await params;
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/sign-in");
  }

  const project = await getProject(id, user.id);

  if (!project) {
    notFound();
  }

  const sources = await getSources(id);

  return (
    <div className="flex flex-col h-full">
      {/* Project header */}
      <div className="border-b px-6 py-3 flex items-center gap-3 bg-background shrink-0">
        <div className="flex-1 min-w-0">
          <h1 className="font-semibold text-base truncate">{project.name}</h1>
          {project.description && (
            <p className="text-xs text-muted-foreground truncate mt-0.5">
              {project.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-muted-foreground">
            {sources.length} {sources.length === 1 ? "source" : "sources"}
          </span>
        </div>
      </div>

      {/* Three-panel workspace */}
      <div className="flex-1 overflow-hidden">
        <ThreePanel
          left={<SourcesPanel projectId={id} sources={sources} />}
          center={<ChatPanel projectId={id} projectName={project.name} />}
          right={<OutputsPanel projectId={id} />}
        />
      </div>
    </div>
  );
}

import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CreateProjectDialog } from "./CreateProjectDialog";
import { FolderOpen, ArrowRight, Calendar } from "lucide-react";

async function getProjects(userId: string) {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("projects")
    .select("*")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });

  if (error) {
    console.error("Error fetching projects:", error);
    return [];
  }
  return data ?? [];
}

export default async function ProjectsPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/sign-in");
  }

  const projects = await getProjects(user.id);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b px-6 py-4 flex items-center justify-between bg-background">
        <div>
          <h1 className="text-xl font-semibold">Projects</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Each project is a workspace for a product, team, or research initiative.
          </p>
        </div>
        <CreateProjectDialog userId={user.id} />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {projects.length === 0 ? (
          <EmptyState userId={user.id} />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 max-w-5xl">
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ProjectCard({ project }: { project: { id: string; name: string; description: string | null; created_at: string } }) {
  const createdAt = new Date(project.created_at).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  return (
    <Link href={`/projects/${project.id}`}>
      <Card className="h-full hover:shadow-md hover:border-primary/30 transition-all cursor-pointer group">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <div className="flex items-center justify-center w-8 h-8 rounded-md bg-primary/10 text-primary shrink-0">
                <FolderOpen className="h-4 w-4" />
              </div>
              <CardTitle className="text-base leading-tight">{project.name}</CardTitle>
            </div>
            <ArrowRight className="h-4 w-4 text-muted-foreground shrink-0 opacity-0 group-hover:opacity-100 transition-opacity mt-0.5" />
          </div>
          {project.description && (
            <CardDescription className="line-clamp-2 mt-1">
              {project.description}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Calendar className="h-3 w-3" />
            <span>Created {createdAt}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

function EmptyState({ userId }: { userId: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center max-w-sm mx-auto">
      <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 text-primary mb-4">
        <FolderOpen className="h-8 w-8" />
      </div>
      <h2 className="text-lg font-semibold mb-2">No projects yet</h2>
      <p className="text-sm text-muted-foreground mb-6">
        Create your first project to start uploading customer feedback and
        discovering product opportunities.
      </p>
      <CreateProjectDialog userId={userId} />
    </div>
  );
}

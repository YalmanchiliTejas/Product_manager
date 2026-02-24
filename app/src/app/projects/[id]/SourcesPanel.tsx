"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, FileText, Trash2, Upload, Tag } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

type Source = {
  id: string;
  name: string;
  source_type: string;
  segment_tags: string[];
  created_at: string;
};

interface SourcesPanelProps {
  projectId: string;
  sources: Source[];
}

const SOURCE_TYPES = [
  { value: "interview", label: "Interview" },
  { value: "support_ticket", label: "Support Ticket" },
  { value: "nps", label: "NPS Feedback" },
  { value: "survey", label: "Survey" },
  { value: "analytics", label: "Analytics" },
  { value: "other", label: "Other" },
];

const SOURCE_TYPE_COLORS: Record<string, string> = {
  interview: "bg-blue-100 text-blue-700",
  support_ticket: "bg-orange-100 text-orange-700",
  nps: "bg-green-100 text-green-700",
  survey: "bg-purple-100 text-purple-700",
  analytics: "bg-yellow-100 text-yellow-700",
  other: "bg-gray-100 text-gray-700",
};

export function SourcesPanel({ projectId, sources }: SourcesPanelProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [sourceType, setSourceType] = useState("interview");
  const [content, setContent] = useState("");
  const [segmentTags, setSegmentTags] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAddSource(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const tags = segmentTags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);

      const res = await fetch("/api/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          name,
          source_type: sourceType,
          raw_content: content,
          segment_tags: tags,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error ?? "Failed to add source");
      }

      // Trigger processing pipeline in background
      if (data.id) {
        fetch("/api/sources/process", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_id: data.id }),
        }).catch(console.error);
      }

      setOpen(false);
      setName("");
      setContent("");
      setSegmentTags("");
      setSourceType("interview");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(sourceId: string) {
    if (!confirm("Delete this source? This will also remove its embeddings.")) return;

    await fetch(`/api/sources/${sourceId}`, { method: "DELETE" });
    router.refresh();
  }

  return (
    <div className="flex flex-col h-full">
      {/* Panel header */}
      <div className="p-4 border-b flex items-center justify-between shrink-0">
        <div>
          <h2 className="text-sm font-semibold">Sources</h2>
          <p className="text-xs text-muted-foreground">{sources.length} uploaded</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" className="gap-1.5">
              <Plus className="h-3.5 w-3.5" />
              Add
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-[520px]">
            <DialogHeader>
              <DialogTitle>Add a source</DialogTitle>
              <DialogDescription>
                Paste customer interview notes, support tickets, NPS responses,
                or any other customer signal.
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleAddSource}>
              <div className="space-y-4 py-4">
                {error && (
                  <div className="rounded-md bg-destructive/10 border border-destructive/20 p-3 text-sm text-destructive">
                    {error}
                  </div>
                )}
                <div className="space-y-2">
                  <Label htmlFor="source-name">Name</Label>
                  <Input
                    id="source-name"
                    placeholder="e.g. Sarah Chen interview — Jan 15"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label>Source type</Label>
                  <div className="flex flex-wrap gap-2">
                    {SOURCE_TYPES.map((type) => (
                      <button
                        key={type.value}
                        type="button"
                        onClick={() => setSourceType(type.value)}
                        className={cn(
                          "px-3 py-1 rounded-full text-xs font-medium border transition-colors",
                          sourceType === type.value
                            ? "bg-primary text-primary-foreground border-primary"
                            : "border-border hover:bg-accent"
                        )}
                      >
                        {type.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="content">Content</Label>
                  <Textarea
                    id="content"
                    placeholder="Paste the raw text of the interview, ticket, or feedback here..."
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    required
                    rows={8}
                    className="resize-none font-mono text-xs"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="segments">
                    Segment tags{" "}
                    <span className="text-muted-foreground font-normal">
                      (comma-separated)
                    </span>
                  </Label>
                  <Input
                    id="segments"
                    placeholder="e.g. enterprise, churned, power-user"
                    value={segmentTags}
                    onChange={(e) => setSegmentTags(e.target.value)}
                  />
                </div>
              </div>
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setOpen(false)}
                  disabled={loading}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={loading || !name.trim() || !content.trim()}
                >
                  {loading ? "Adding..." : "Add source"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {/* Sources list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {sources.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center px-4">
            <Upload className="h-8 w-8 text-muted-foreground mb-3" />
            <p className="text-sm font-medium mb-1">No sources yet</p>
            <p className="text-xs text-muted-foreground">
              Add customer interviews, support tickets, or other feedback to
              start discovering insights.
            </p>
          </div>
        ) : (
          sources.map((source) => (
            <SourceCard
              key={source.id}
              source={source}
              onDelete={handleDelete}
            />
          ))
        )}
      </div>
    </div>
  );
}

function SourceCard({
  source,
  onDelete,
}: {
  source: Source;
  onDelete: (id: string) => void;
}) {
  const typeColor =
    SOURCE_TYPE_COLORS[source.source_type] ?? SOURCE_TYPE_COLORS.other;
  const typeLabel =
    SOURCE_TYPES.find((t) => t.value === source.source_type)?.label ??
    source.source_type;

  return (
    <div className="group flex items-start gap-2 p-3 rounded-lg border bg-card hover:bg-accent/30 transition-colors">
      <div className="flex items-center justify-center w-7 h-7 rounded-md bg-muted shrink-0 mt-0.5">
        <FileText className="h-3.5 w-3.5 text-muted-foreground" />
      </div>
      <div className="flex-1 min-w-0 space-y-1.5">
        <p className="text-sm font-medium truncate">{source.name}</p>
        <div className="flex flex-wrap gap-1">
          <span
            className={cn(
              "inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium",
              typeColor
            )}
          >
            {typeLabel}
          </span>
          {source.segment_tags?.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs bg-muted text-muted-foreground"
            >
              <Tag className="h-2.5 w-2.5" />
              {tag}
            </span>
          ))}
        </div>
      </div>
      <button
        onClick={() => onDelete(source.id)}
        className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive shrink-0"
        aria-label="Delete source"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

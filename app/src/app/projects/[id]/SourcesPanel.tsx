"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useDropzone } from "react-dropzone";
import {
  Plus,
  FileText,
  Trash2,
  Upload,
  Tag,
  X,
  Loader2,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
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

type SourceStatus = "processing" | "done" | "error";

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

const ACCEPTED_TYPES = {
  "text/plain": [".txt"],
  "text/markdown": [".md"],
  "text/csv": [".csv"],
  "application/json": [".json"],
  "text/x-markdown": [".md"],
};

function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => resolve((e.target?.result as string) ?? "");
    reader.onerror = () => reject(new Error(`Failed to read file: ${file.name}`));
    reader.readAsText(file);
  });
}

function stripExtension(filename: string) {
  return filename.replace(/\.[^/.]+$/, "");
}

export function SourcesPanel({ projectId, sources }: SourcesPanelProps) {
  const router = useRouter();

  // Dialog state
  const [open, setOpen] = useState(false);
  const [dialogTab, setDialogTab] = useState<"paste" | "upload">("paste");

  // Paste form
  const [name, setName] = useState("");
  const [sourceType, setSourceType] = useState("interview");
  const [content, setContent] = useState("");
  const [segmentTags, setSegmentTags] = useState("");

  // Upload form
  const [droppedFiles, setDroppedFiles] = useState<File[]>([]);
  const [uploadSourceType, setUploadSourceType] = useState("interview");
  const [uploadSegmentTags, setUploadSegmentTags] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Per-source processing status (session-only)
  const [sourceStatuses, setSourceStatuses] = useState<Record<string, SourceStatus>>({});

  // --- dropzone ---
  const onDrop = useCallback((accepted: File[]) => {
    setDroppedFiles((prev) => {
      const existingNames = new Set(prev.map((f) => f.name));
      return [...prev, ...accepted.filter((f) => !existingNames.has(f.name))];
    });
    setError(null);
  }, []);

  const onDropRejected = useCallback(() => {
    setError("Only .txt, .md, .csv, and .json files are supported.");
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected,
    accept: ACCEPTED_TYPES,
    multiple: true,
  });

  function removeFile(name: string) {
    setDroppedFiles((prev) => prev.filter((f) => f.name !== name));
  }

  // --- core logic ---
  async function triggerProcessing(sourceId: string) {
    setSourceStatuses((prev) => ({ ...prev, [sourceId]: "processing" }));
    try {
      const res = await fetch("/api/sources/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_id: sourceId }),
      });
      setSourceStatuses((prev) => ({
        ...prev,
        [sourceId]: res.ok ? "done" : "error",
      }));
    } catch {
      setSourceStatuses((prev) => ({ ...prev, [sourceId]: "error" }));
    }
  }

  async function createSource(payload: {
    name: string;
    source_type: string;
    raw_content: string;
    segment_tags: string[];
  }): Promise<string | null> {
    const res = await fetch("/api/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, ...payload }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error ?? "Failed to add source");
    return data.id ?? null;
  }

  // Paste submit
  async function handlePasteSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const tags = segmentTags.split(",").map((t) => t.trim()).filter(Boolean);
      const id = await createSource({ name, source_type: sourceType, raw_content: content, segment_tags: tags });
      if (id) triggerProcessing(id);
      resetAndClose();
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  // Upload submit
  async function handleUploadSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (droppedFiles.length === 0) return;
    setError(null);
    setLoading(true);
    try {
      const tags = uploadSegmentTags.split(",").map((t) => t.trim()).filter(Boolean);
      const results = await Promise.allSettled(
        droppedFiles.map(async (file) => {
          const text = await readFileAsText(file);
          const id = await createSource({
            name: stripExtension(file.name),
            source_type: uploadSourceType,
            raw_content: text,
            segment_tags: tags,
          });
          if (id) triggerProcessing(id);
        })
      );
      const failures = results.filter((r) => r.status === "rejected");
      if (failures.length > 0) {
        setError(`${failures.length} file(s) failed to upload.`);
      }
      resetAndClose();
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  function resetAndClose() {
    setOpen(false);
    setName("");
    setContent("");
    setSegmentTags("");
    setSourceType("interview");
    setDroppedFiles([]);
    setUploadSourceType("interview");
    setUploadSegmentTags("");
    setError(null);
    setDialogTab("paste");
  }

  async function handleDelete(sourceId: string) {
    if (!confirm("Delete this source? This will also remove its embeddings.")) return;
    await fetch(`/api/sources/${sourceId}`, { method: "DELETE" });
    setSourceStatuses((prev) => {
      const next = { ...prev };
      delete next[sourceId];
      return next;
    });
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
        <Dialog open={open} onOpenChange={(v) => { if (!v) resetAndClose(); else setOpen(true); }}>
          <DialogTrigger asChild>
            <Button size="sm" className="gap-1.5">
              <Plus className="h-3.5 w-3.5" />
              Add
            </Button>
          </DialogTrigger>

          <DialogContent className="sm:max-w-[540px]">
            <DialogHeader>
              <DialogTitle>Add a source</DialogTitle>
            </DialogHeader>

            {/* Tabs */}
            <div className="flex gap-1 p-1 bg-muted rounded-lg">
              {(["paste", "upload"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() => { setDialogTab(tab); setError(null); }}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                    dialogTab === tab
                      ? "bg-background shadow-sm text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {tab === "paste" ? (
                    <><FileText className="h-3.5 w-3.5" /> Paste text</>
                  ) : (
                    <><Upload className="h-3.5 w-3.5" /> Upload files</>
                  )}
                </button>
              ))}
            </div>

            {error && (
              <div className="rounded-md bg-destructive/10 border border-destructive/20 p-3 text-sm text-destructive">
                {error}
              </div>
            )}

            {/* Paste Tab */}
            {dialogTab === "paste" && (
              <form onSubmit={handlePasteSubmit}>
                <div className="space-y-4 py-2">
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
                  <SourceTypeSelector value={sourceType} onChange={setSourceType} />
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
                  <SegmentTagsInput value={segmentTags} onChange={setSegmentTags} />
                </div>
                <DialogFooter className="mt-4">
                  <Button type="button" variant="outline" onClick={resetAndClose} disabled={loading}>
                    Cancel
                  </Button>
                  <Button type="submit" disabled={loading || !name.trim() || !content.trim()}>
                    {loading ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Adding...</> : "Add source"}
                  </Button>
                </DialogFooter>
              </form>
            )}

            {/* Upload Tab */}
            {dialogTab === "upload" && (
              <form onSubmit={handleUploadSubmit}>
                <div className="space-y-4 py-2">
                  {/* Dropzone */}
                  <div
                    {...getRootProps()}
                    className={cn(
                      "border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors",
                      isDragActive
                        ? "border-primary bg-primary/5"
                        : "border-border hover:border-primary/50 hover:bg-accent/30"
                    )}
                  >
                    <input {...getInputProps()} />
                    <Upload className="h-7 w-7 mx-auto mb-2 text-muted-foreground" />
                    {isDragActive ? (
                      <p className="text-sm font-medium text-primary">Drop files here</p>
                    ) : (
                      <>
                        <p className="text-sm font-medium">
                          Drag & drop files, or{" "}
                          <span className="text-primary underline underline-offset-2">browse</span>
                        </p>
                        <p className="text-xs text-muted-foreground mt-1">
                          Supports .txt, .md, .csv, .json — multiple files at once
                        </p>
                      </>
                    )}
                  </div>

                  {/* File list */}
                  {droppedFiles.length > 0 && (
                    <div className="space-y-1.5">
                      <p className="text-xs font-medium text-muted-foreground">
                        {droppedFiles.length} file{droppedFiles.length > 1 ? "s" : ""} selected
                      </p>
                      <div className="max-h-32 overflow-y-auto space-y-1">
                        {droppedFiles.map((file) => (
                          <div
                            key={file.name}
                            className="flex items-center gap-2 px-2.5 py-1.5 rounded-md bg-muted text-sm"
                          >
                            <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                            <span className="flex-1 truncate text-xs">{file.name}</span>
                            <span className="text-xs text-muted-foreground shrink-0">
                              {(file.size / 1024).toFixed(0)} KB
                            </span>
                            <button
                              type="button"
                              onClick={() => removeFile(file.name)}
                              className="text-muted-foreground hover:text-destructive transition-colors shrink-0"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <SourceTypeSelector value={uploadSourceType} onChange={setUploadSourceType} />
                  <SegmentTagsInput value={uploadSegmentTags} onChange={setUploadSegmentTags} />
                </div>

                <DialogFooter className="mt-4">
                  <Button type="button" variant="outline" onClick={resetAndClose} disabled={loading}>
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    disabled={loading || droppedFiles.length === 0}
                  >
                    {loading ? (
                      <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Uploading...</>
                    ) : (
                      `Upload ${droppedFiles.length > 0 ? droppedFiles.length + " " : ""}file${droppedFiles.length !== 1 ? "s" : ""}`
                    )}
                  </Button>
                </DialogFooter>
              </form>
            )}
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
              status={sourceStatuses[source.id]}
              onDelete={handleDelete}
            />
          ))
        )}
      </div>
    </div>
  );
}

// --- Shared sub-components ---

function SourceTypeSelector({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="space-y-2">
      <Label>Source type</Label>
      <div className="flex flex-wrap gap-2">
        {SOURCE_TYPES.map((type) => (
          <button
            key={type.value}
            type="button"
            onClick={() => onChange(type.value)}
            className={cn(
              "px-3 py-1 rounded-full text-xs font-medium border transition-colors",
              value === type.value
                ? "bg-primary text-primary-foreground border-primary"
                : "border-border hover:bg-accent"
            )}
          >
            {type.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function SegmentTagsInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="space-y-2">
      <Label htmlFor="segments">
        Segment tags{" "}
        <span className="text-muted-foreground font-normal">(comma-separated)</span>
      </Label>
      <Input
        id="segments"
        placeholder="e.g. enterprise, churned, power-user"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function SourceCard({
  source,
  status,
  onDelete,
}: {
  source: Source;
  status?: SourceStatus;
  onDelete: (id: string) => void;
}) {
  const typeColor = SOURCE_TYPE_COLORS[source.source_type] ?? SOURCE_TYPE_COLORS.other;
  const typeLabel =
    SOURCE_TYPES.find((t) => t.value === source.source_type)?.label ?? source.source_type;

  return (
    <div className="group flex items-start gap-2 p-3 rounded-lg border bg-card hover:bg-accent/30 transition-colors">
      <div className="flex items-center justify-center w-7 h-7 rounded-md bg-muted shrink-0 mt-0.5">
        {status === "processing" ? (
          <Loader2 className="h-3.5 w-3.5 text-muted-foreground animate-spin" />
        ) : status === "done" ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
        ) : status === "error" ? (
          <AlertCircle className="h-3.5 w-3.5 text-destructive" />
        ) : (
          <FileText className="h-3.5 w-3.5 text-muted-foreground" />
        )}
      </div>
      <div className="flex-1 min-w-0 space-y-1.5">
        <div className="flex items-center gap-1.5">
          <p className="text-sm font-medium truncate">{source.name}</p>
          {status === "processing" && (
            <span className="text-xs text-muted-foreground shrink-0">Processing...</span>
          )}
          {status === "error" && (
            <span className="text-xs text-destructive shrink-0">Failed</span>
          )}
        </div>
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

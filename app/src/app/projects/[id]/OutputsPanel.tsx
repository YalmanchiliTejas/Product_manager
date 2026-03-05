"use client";

import { useState } from "react";
import { Lightbulb, Zap, BarChart3, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface OutputsPanelProps {
  projectId: string;
}

type OutputTab = "opportunities" | "themes" | "synthesis";

export function OutputsPanel({ projectId }: OutputsPanelProps) {
  const [activeTab, setActiveTab] = useState<OutputTab>("opportunities");

  const tabs: { key: OutputTab; label: string; icon: React.ElementType }[] = [
    { key: "opportunities", label: "Opportunities", icon: Lightbulb },
    { key: "themes", label: "Themes", icon: BarChart3 },
    { key: "synthesis", label: "Synthesis", icon: Zap },
  ];

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Panel header */}
      <div className="p-4 border-b shrink-0">
        <h2 className="text-sm font-semibold">Outputs</h2>
        <p className="text-xs text-muted-foreground">
          AI-generated insights from your sources
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b shrink-0">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={cn(
                "flex-1 flex items-center justify-center gap-1.5 py-2.5 text-xs font-medium transition-colors border-b-2",
                activeTab === tab.key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === "opportunities" && <OpportunitiesTab projectId={projectId} />}
        {activeTab === "themes" && <ThemesTab projectId={projectId} />}
        {activeTab === "synthesis" && <SynthesisTab projectId={projectId} />}
      </div>
    </div>
  );
}

function OpportunitiesTab({ projectId }: { projectId: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 text-center h-full">
      <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-yellow-50 text-yellow-600 mb-4">
        <Lightbulb className="h-6 w-6" />
      </div>
      <h3 className="text-sm font-semibold mb-2">No opportunities yet</h3>
      <p className="text-xs text-muted-foreground mb-4 max-w-[200px]">
        Add sources and run a synthesis to generate prioritized product opportunities.
      </p>
      <Button variant="outline" size="sm" className="gap-2" disabled>
        <Zap className="h-3.5 w-3.5" />
        Run synthesis
      </Button>
      <p className="text-xs text-muted-foreground mt-2">
        Coming in Week 3
      </p>
    </div>
  );
}

function ThemesTab({ projectId }: { projectId: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 text-center h-full">
      <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-blue-50 text-blue-600 mb-4">
        <BarChart3 className="h-6 w-6" />
      </div>
      <h3 className="text-sm font-semibold mb-2">No themes extracted</h3>
      <p className="text-xs text-muted-foreground max-w-[200px]">
        Themes are automatically identified when you run synthesis on your sources.
      </p>
      <p className="text-xs text-muted-foreground mt-3">Coming in Week 3</p>
    </div>
  );
}

function SynthesisTab({ projectId }: { projectId: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 text-center h-full">
      <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-purple-50 text-purple-600 mb-4">
        <Zap className="h-6 w-6" />
      </div>
      <h3 className="text-sm font-semibold mb-2">Ready to synthesize</h3>
      <p className="text-xs text-muted-foreground mb-4 max-w-[200px]">
        Once you&apos;ve added sources, trigger a synthesis to run the full
        AI analysis pipeline across all your customer data.
      </p>
      <Button variant="outline" size="sm" className="gap-2" disabled>
        <Zap className="h-3.5 w-3.5" />
        Synthesize now
      </Button>
      <p className="text-xs text-muted-foreground mt-2">Coming in Week 3</p>
    </div>
  );
}

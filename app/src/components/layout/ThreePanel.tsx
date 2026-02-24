import { cn } from "@/lib/utils";

interface ThreePanelProps {
  left: React.ReactNode;
  center: React.ReactNode;
  right: React.ReactNode;
  className?: string;
}

/**
 * Three-panel layout: Sources | Chat | Outputs
 * Matches the core Beacon workspace paradigm from the product plan.
 */
export function ThreePanel({ left, center, right, className }: ThreePanelProps) {
  return (
    <div className={cn("flex h-full w-full overflow-hidden", className)}>
      {/* Left panel — Sources */}
      <div className="w-72 shrink-0 border-r flex flex-col overflow-hidden">
        {left}
      </div>

      {/* Center panel — Chat (primary interaction) */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {center}
      </div>

      {/* Right panel — Outputs */}
      <div className="w-80 shrink-0 border-l flex flex-col overflow-hidden">
        {right}
      </div>
    </div>
  );
}

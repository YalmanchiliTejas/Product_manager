import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { Button } from "@/components/ui/button";
import { ArrowRight, Zap, MessageSquare, Lightbulb } from "lucide-react";

export default async function LandingPage() {
  // Redirect authenticated users straight to their projects
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (user) {
    redirect("/projects");
  }

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Nav */}
      <header className="border-b px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary text-primary-foreground font-bold text-sm">
            B
          </div>
          <span className="font-semibold">Beacon</span>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/sign-in">
            <Button variant="ghost" size="sm">
              Sign in
            </Button>
          </Link>
          <Link href="/sign-up">
            <Button size="sm" className="gap-2">
              Get started
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </Link>
        </div>
      </header>

      {/* Hero */}
      <main className="flex-1 flex flex-col items-center justify-center px-6 py-20 text-center">
        <div className="max-w-3xl space-y-6">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border text-sm text-muted-foreground bg-muted/50 mb-2">
            <Zap className="h-3.5 w-3.5 text-primary" />
            Cursor for Product Managers
          </div>

          <h1 className="text-4xl md:text-6xl font-bold tracking-tight text-foreground">
            Discover what to{" "}
            <span className="text-primary">build next</span>
          </h1>

          <p className="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto leading-relaxed">
            Upload customer interviews, support tickets, and feedback. Ask
            Beacon what matters most. Get evidence-backed product opportunities
            in minutes, not days.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
            <Link href="/sign-up">
              <Button size="lg" className="gap-2 px-8">
                Start for free
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
            <Link href="/sign-in">
              <Button variant="outline" size="lg">
                Sign in
              </Button>
            </Link>
          </div>
          <p className="text-xs text-muted-foreground">
            No credit card required
          </p>
        </div>

        {/* Feature highlights */}
        <div className="mt-20 grid grid-cols-1 md:grid-cols-3 gap-6 max-w-4xl w-full">
          <FeatureCard
            icon={Zap}
            title="Ingest any signal"
            description="Upload interviews, support tickets, NPS responses, and surveys. Beacon extracts and indexes every insight."
          />
          <FeatureCard
            icon={MessageSquare}
            title="Chat with your data"
            description="Ask &ldquo;What should we build next?&rdquo; and get direct answers grounded in customer quotes."
          />
          <FeatureCard
            icon={Lightbulb}
            title="Evidence-backed opportunities"
            description="Every insight links to source material. No hallucinations. No guessing. Just clear, ranked opportunities."
          />
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t px-6 py-4 text-center text-xs text-muted-foreground">
        Beacon — AI Product Discovery Engine
      </footer>
    </div>
  );
}

function FeatureCard({
  icon: Icon,
  title,
  description,
}: {
  icon: React.ElementType;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col items-start text-left p-6 rounded-xl border bg-card">
      <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary mb-4">
        <Icon className="h-5 w-5" />
      </div>
      <h3 className="font-semibold mb-2">{title}</h3>
      <p className="text-sm text-muted-foreground leading-relaxed">
        {description}
      </p>
    </div>
  );
}

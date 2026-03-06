"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Zap, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface ChatPanelProps {
  projectId: string;
  projectName: string;
}

const SUGGESTED_PROMPTS = [
  "What are the most common pain points?",
  "What should we build next?",
  "Which issues affect enterprise users most?",
  "Summarize key themes across all sources",
];

export function ChatPanel({ projectId, projectName }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(content?: string) {
    const messageContent = content ?? input.trim();
    if (!messageContent || loading) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: messageContent,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    try {
      // Placeholder: will be wired to /api/chat in Week 3
      await new Promise((resolve) => setTimeout(resolve, 1000));

      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content:
          "The AI chat pipeline is coming in Week 3. For now, add sources in the left panel to build your knowledge base, then come back to analyze them here.",
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Panel header */}
      <div className="p-4 border-b shrink-0">
        <h2 className="text-sm font-semibold">Chat</h2>
        <p className="text-xs text-muted-foreground">
          Ask questions about your customer data
        </p>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <EmptyChat projectName={projectName} onPromptClick={handleSend} />
        ) : (
          <>
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {loading && <TypingIndicator />}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input area */}
      <div className="p-4 border-t shrink-0">
        <div className="flex gap-2 items-end">
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your customer data... (Enter to send)"
            rows={2}
            className="resize-none text-sm"
          />
          <Button
            size="icon"
            onClick={() => handleSend()}
            disabled={!input.trim() || loading}
            className="shrink-0"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
        <p className="text-xs text-muted-foreground mt-2">
          Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}

function EmptyChat({
  projectName,
  onPromptClick,
}: {
  projectName: string;
  onPromptClick: (prompt: string) => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center h-full py-8 px-4 text-center">
      <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-primary/10 text-primary mb-4">
        <MessageSquare className="h-6 w-6" />
      </div>
      <h3 className="text-base font-semibold mb-1">
        Chat with your data
      </h3>
      <p className="text-sm text-muted-foreground mb-6 max-w-xs">
        Ask questions about your customer signals and Beacon will analyze them
        with evidence from your sources.
      </p>
      <div className="space-y-2 w-full max-w-xs">
        {SUGGESTED_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            onClick={() => onPromptClick(prompt)}
            className="w-full text-left px-3 py-2 rounded-lg border text-sm hover:bg-accent transition-colors"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex items-center justify-center w-7 h-7 rounded-full shrink-0 text-xs font-semibold",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground"
        )}
      >
        {isUser ? "U" : "B"}
      </div>
      <div
        className={cn(
          "max-w-[80%] rounded-xl px-4 py-2.5 text-sm",
          isUser
            ? "bg-primary text-primary-foreground rounded-tr-sm"
            : "bg-muted text-foreground rounded-tl-sm"
        )}
      >
        <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
        <p
          className={cn(
            "text-xs mt-1 opacity-60",
            isUser ? "text-right" : "text-left"
          )}
        >
          {message.timestamp.toLocaleTimeString("en-US", {
            hour: "numeric",
            minute: "2-digit",
          })}
        </p>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex gap-3">
      <div className="flex items-center justify-center w-7 h-7 rounded-full bg-muted text-muted-foreground text-xs font-semibold shrink-0">
        B
      </div>
      <div className="bg-muted rounded-xl rounded-tl-sm px-4 py-3">
        <div className="flex gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce [animation-delay:-0.3s]" />
          <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce [animation-delay:-0.15s]" />
          <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" />
        </div>
      </div>
    </div>
  );
}

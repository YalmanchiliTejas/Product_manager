import Anthropic from "@anthropic-ai/sdk";

// Lazy singleton — instantiated once per cold start.
let _client: Anthropic | null = null;

export function getClaudeClient(): Anthropic {
  if (!_client) {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) throw new Error("ANTHROPIC_API_KEY is required.");
    _client = new Anthropic({ apiKey });
  }
  return _client;
}

// Model aliases used across the synthesis pipeline.
export const CLAUDE_FAST = "claude-haiku-4-5";   // Map phase — fast, cheap
export const CLAUDE_BALANCED = "claude-sonnet-4-5"; // Reduce + chat — good reasoning
export const CLAUDE_DEEP = "claude-opus-4-5";      // Opportunity scoring — best reasoning

/**
 * Single, non-streaming call that returns the full assistant text.
 * Automatically requests JSON via the Anthropic beta when `json` is true.
 */
export async function complete(
  model: string,
  system: string,
  userContent: string,
  maxTokens = 4096
): Promise<string> {
  const client = getClaudeClient();

  const msg = await client.messages.create({
    model,
    max_tokens: maxTokens,
    system,
    messages: [{ role: "user", content: userContent }],
  });

  const block = msg.content[0];
  if (block.type !== "text") throw new Error("Unexpected response type from Claude.");
  return block.text;
}

/**
 * Same as `complete` but parses the response as JSON.
 * Wraps the output in a try/catch and throws a descriptive error on parse failure.
 */
export async function completeJSON<T = unknown>(
  model: string,
  system: string,
  userContent: string,
  maxTokens = 4096
): Promise<T> {
  const raw = await complete(model, system, userContent, maxTokens);

  // Strip markdown code fences if the model wrapped the JSON in ```json ... ```
  const stripped = raw.replace(/^```(?:json)?\s*/i, "").replace(/\s*```\s*$/, "").trim();

  try {
    return JSON.parse(stripped) as T;
  } catch {
    throw new Error(`Claude returned invalid JSON:\n${raw.slice(0, 500)}`);
  }
}

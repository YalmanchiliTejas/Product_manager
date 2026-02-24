/**
 * Context Manager — token-budget-aware context assembly.
 *
 * Claude's context window is large (200k tokens for Sonnet/Opus), but for
 * the synthesis pipeline we want predictable, cost-controlled requests.
 * We use a rough 4-chars-per-token estimate which is accurate enough for
 * English prose.  The actual tokenizer would be more precise but adds
 * unnecessary runtime overhead here.
 */

const CHARS_PER_TOKEN = 4;

/** Rough token count estimate for a string. */
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / CHARS_PER_TOKEN);
}

export interface ContextItem {
  text: string;
  label?: string; // optional heading shown before the text in the prompt
  metadata?: Record<string, unknown>;
}

export interface PackedContext {
  items: ContextItem[];
  estimatedTokens: number;
  truncated: boolean; // true if some items were dropped to fit the budget
}

/**
 * Greedily pack items into a token budget.
 * Items are taken in the order provided; once the budget is exceeded the
 * remaining items are dropped (set truncated = true).
 *
 * @param items    Content items to pack
 * @param budget   Max tokens to allow
 * @param reserve  Extra tokens to reserve for the system prompt + response
 *                 (subtracted from budget before packing).
 */
export function packIntoContext(
  items: ContextItem[],
  budget: number,
  reserve = 0
): PackedContext {
  const effective = Math.max(budget - reserve, 0);
  const result: ContextItem[] = [];
  let used = 0;

  for (const item of items) {
    const tokens = estimateTokens(item.text + (item.label ?? ""));
    if (used + tokens > effective) {
      return { items: result, estimatedTokens: used, truncated: true };
    }
    result.push(item);
    used += tokens;
  }

  return { items: result, estimatedTokens: used, truncated: false };
}

/**
 * Render a packed context into a single prompt string.
 * Each item is prefixed with its label (if any) as a markdown heading.
 */
export function renderContext(packed: PackedContext, separator = "\n\n---\n\n"): string {
  return packed.items
    .map((item) => (item.label ? `### ${item.label}\n${item.text}` : item.text))
    .join(separator);
}

/**
 * Split a large list of items into batches that each fit within a token budget.
 * Useful for the Map phase when processing many sources in parallel groups.
 */
export function batchByTokenBudget(
  items: ContextItem[],
  budgetPerBatch: number
): ContextItem[][] {
  const batches: ContextItem[][] = [];
  let currentBatch: ContextItem[] = [];
  let currentTokens = 0;

  for (const item of items) {
    const tokens = estimateTokens(item.text + (item.label ?? ""));
    if (currentTokens + tokens > budgetPerBatch && currentBatch.length > 0) {
      batches.push(currentBatch);
      currentBatch = [];
      currentTokens = 0;
    }
    currentBatch.push(item);
    currentTokens += tokens;
  }

  if (currentBatch.length > 0) {
    batches.push(currentBatch);
  }

  return batches;
}

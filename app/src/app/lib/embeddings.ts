const EMBEDDING_MODEL = process.env.EMBEDDING_MODEL ?? "text-embedding-3-small";

export async function createEmbedding(input: string): Promise<number[]> {
  const normalized = input.trim();

  if (!normalized) {
    return [];
  }

  const apiKey = process.env.OPENAI_API_KEY;

  if (!apiKey) {
    throw new Error("OPENAI_API_KEY is required for embedding generation.");
  }

  const response = await fetch("https://api.openai.com/v1/embeddings", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: EMBEDDING_MODEL,
      input: normalized,
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Embedding API failed: ${response.status} ${text}`);
  }

  const payload = (await response.json()) as {
    data?: Array<{ embedding?: number[] }>;
  };

  const embedding = payload.data?.[0]?.embedding;

  if (!embedding?.length) {
    throw new Error("Embedding API returned an empty embedding.");
  }

  return embedding;
}

export function toPgVectorLiteral(vector: number[]): string {
  return `[${vector.join(",")}]`;
}

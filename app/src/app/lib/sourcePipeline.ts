import fs from "node:fs/promises";

export function chunkText(text: string, chunkSize = 1200, overlap = 150): string[] {
  const normalized = text.replace(/\s+/g, " ").trim();

  if (!normalized) {
    return [];
  }

  const chunks: string[] = [];
  let cursor = 0;

  while (cursor < normalized.length) {
    const end = Math.min(cursor + chunkSize, normalized.length);
    chunks.push(normalized.slice(cursor, end));

    if (end >= normalized.length) {
      break;
    }

    cursor = Math.max(end - overlap, cursor + 1);
  }

  return chunks;
}

export async function extractSourceText(rawContent: string | null, filePath: string | null) {
  if (rawContent?.trim()) {
    return rawContent;
  }

  if (!filePath?.trim()) {
    throw new Error("Source has neither raw_content nor file_path.");
  }

  const buffer = await fs.readFile(filePath);

  if (filePath.endsWith(".txt") || filePath.endsWith(".md") || filePath.endsWith(".csv")) {
    return buffer.toString("utf8");
  }

  if (filePath.endsWith(".json")) {
    // Flatten JSON to plain text so it can be chunked and embedded.
    // Arrays of objects (e.g. support-ticket exports) are joined as
    // newline-delimited entries so each record stays coherent after chunking.
    const parsed: unknown = JSON.parse(buffer.toString("utf8"));
    if (Array.isArray(parsed)) {
      return parsed.map((item) => JSON.stringify(item)).join("\n");
    }
    return JSON.stringify(parsed, null, 2);
  }

  throw new Error(
    "Unsupported file type. Supported: .txt, .md, .csv, .json or provide raw_content."
  );
}

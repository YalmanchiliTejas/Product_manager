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

  throw new Error(
    "Unsupported file type for extraction. Supported: .txt, .md, .csv or provide raw_content."
  );
}

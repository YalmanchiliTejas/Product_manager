/**
 * Thin helper for calling the Python orchestration service.
 *
 * Set PYTHON_SERVICE_URL in your environment:
 *   Local dev: http://localhost:8000   (default)
 *   Production: https://your-orchestration-service.railway.app
 */
export const PYTHON_SERVICE_URL =
  (process.env.PYTHON_SERVICE_URL ?? "http://localhost:8000").replace(/\/$/, "");

/**
 * Forward a JSON request to the Python service and return a JSON response.
 * Preserves the upstream HTTP status code.
 */
export async function proxyJSON(
  path: string,
  body: unknown
): Promise<{ data: unknown; status: number }> {
  const res = await fetch(`${PYTHON_SERVICE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const data = await res.json().catch(() => ({ error: "Invalid response from orchestration service." }));
  return { data, status: res.status };
}

/**
 * Forward a streaming request to the Python service and return the raw
 * ReadableStream so Next.js can pipe it directly to the client.
 */
export async function proxyStream(
  path: string,
  body: unknown
): Promise<Response> {
  const res = await fetch(`${PYTHON_SERVICE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "Orchestration service error.");
    return new Response(JSON.stringify({ error: text }), {
      status: res.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(res.body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Transfer-Encoding": "chunked",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

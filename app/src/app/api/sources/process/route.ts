/**
 * POST /api/sources/process
 * Proxies to the Python orchestration service → POST /process
 */
import { NextResponse } from "next/server";
import { proxyJSON } from "@/app/lib/pythonService";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const { data, status } = await proxyJSON("/process", body);
  return NextResponse.json(data, { status });
}

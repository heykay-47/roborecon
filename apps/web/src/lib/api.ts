const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, statusText: string, detail?: string) {
    super(detail || `API error: ${status} ${statusText}`);
    this.name = "ApiError";
    this.status = status;
  }
}

async function readBody(response: Response): Promise<unknown> {
  const body = await response.text();
  if (!body.trim()) return undefined;

  try {
    return JSON.parse(body) as unknown;
  } catch {
    return body;
  }
}

function errorDetail(body: unknown): string | undefined {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return undefined;
  }
  const detail = body.detail;
  return typeof detail === "string" ? detail : JSON.stringify(detail);
}

export async function fetchApi<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });

  if (!response.ok) {
    const body = await readBody(response);
    throw new ApiError(response.status, response.statusText, errorDetail(body));
  }

  return (await readBody(response)) as T;
}

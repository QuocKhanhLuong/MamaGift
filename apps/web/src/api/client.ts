import type { ApiErrorBody } from "./types";

export const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

/** A structured API error, or a client-side connectivity failure (no server evidence). */
export class ApiRequestError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly requestId: string | null;
  readonly details: Record<string, unknown>;
  readonly offline: boolean;

  constructor(options: {
    code: string;
    message: string;
    retryable: boolean;
    requestId: string | null;
    details?: Record<string, unknown>;
    offline?: boolean;
  }) {
    super(options.message);
    this.code = options.code;
    this.retryable = options.retryable;
    this.requestId = options.requestId;
    this.details = options.details ?? {};
    this.offline = options.offline ?? false;
  }
}

async function parseErrorBody(response: Response): Promise<ApiErrorBody | null> {
  try {
    const payload = (await response.json()) as { error?: ApiErrorBody };
    return payload.error ?? null;
  } catch {
    return null;
  }
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: BodyInit | object | null;
  signal?: AbortSignal;
}

/**
 * A thin fetch wrapper that converts the documented error envelope
 * (`docs/08_API_AND_DATA_CONTRACTS.md` section 19) and network failures into one
 * `ApiRequestError`, so the UI never has to guess whether a failure is a rejection or
 * a connectivity problem.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, headers, ...rest } = options;
  const isJsonBody =
    body !== null && body !== undefined && !(body instanceof FormData) && typeof body === "object";

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      headers: isJsonBody ? { "Content-Type": "application/json", ...headers } : headers,
      body: isJsonBody ? JSON.stringify(body) : (body as BodyInit | null | undefined),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiRequestError({
      code: "network_unavailable",
      message: "Không thể kết nối tới máy chủ.",
      retryable: true,
      requestId: null,
      offline: true,
    });
  }

  if (!response.ok) {
    const errorBody = await parseErrorBody(response);
    if (errorBody) {
      throw new ApiRequestError({
        code: errorBody.code,
        message: errorBody.message,
        retryable: errorBody.retryable,
        requestId: errorBody.request_id,
        details: errorBody.details,
      });
    }
    throw new ApiRequestError({
      code: "internal_error",
      message: `Máy chủ trả về lỗi ${response.status}.`,
      retryable: response.status >= 500,
      requestId: response.headers.get("x-request-id"),
    });
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

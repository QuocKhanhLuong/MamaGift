import { apiRequest } from "./client";

export interface HealthResponse {
  status: "ok";
  service: "api";
  version: string;
}

export function checkHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/health", { signal });
}

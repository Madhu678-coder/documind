import type {
  QuestionDraftRequest,
  QuestionDraftResponse,
  RunCreatePayload,
  RunDetail,
  RunSummary,
} from "./types";

const BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  if (res.status === 204) return undefined as unknown as T;
  return res.json() as Promise<T>;
}

export const api = {
  listRuns: () => request<RunSummary[]>("/runs"),
  getRun: (id: string) => request<RunDetail>(`/runs/${id}`),
  createRun: (payload: RunCreatePayload) =>
    request<RunDetail>("/runs", { method: "POST", body: JSON.stringify(payload) }),
  deleteRun: (id: string) => request<void>(`/runs/${id}`, { method: "DELETE" }),
  exportUrl: (id: string) => `${BASE}/runs/${id}/export`,
  generateQuestionDrafts: (payload: QuestionDraftRequest) =>
    request<QuestionDraftResponse>("/question-drafts", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function del_<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = { method: "POST" };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export function sourceImageUrl(sourceName: string, recordId: number): string {
  return `${BASE}/sources/${sourceName}/records/${recordId}/image`;
}

export interface Episode {
  id: number;
  summary: string;
  app_names: string;
  frame_count: number;
  started_at: string;
  ended_at: string;
  created_at: string;
}

export interface Playbook {
  id: number;
  name: string;
  context: string;
  action: string;
  confidence: number;
  maturity: string;
  evidence: string;
  updated_at: string;
}

export interface Routine {
  id: number;
  name: string;
  trigger: string;
  goal: string;
  steps: string;
  uses: string;
  confidence: number;
  maturity: string;
  updated_at: string;
}

export interface Insight {
  id: number;
  title: string;
  body: string;
  category: string;
  evidence: string;
  data: string;
  run_id: string;
  created_at: string;
}

export interface DaGoal {
  id: number;
  goal: string;
  status: string;
  progress_notes: string;
  created_at: string;
  updated_at: string;
}

export interface ScmTask {
  id: number;
  project: string;
  title: string;
  status: string;
  evidence: string;
  notes: string;
  run_id: string;
  created_at: string;
  updated_at: string;
}

export interface UsageSummary {
  days: number;
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_calls: number;
  by_layer: {
    layer: string;
    model: string;
    total_input: number;
    total_output: number;
    total_cost: number;
    call_count: number;
  }[];
  by_day: {
    day: string;
    total_input: number;
    total_output: number;
    total_cost: number;
    call_count: number;
  }[];
}

export interface SourceManifest {
  name: string;
  display_name: string;
  description: string;
  db: {
    table: string;
    columns: Record<string, string>;
  };
  ui: {
    icon: string;
    visible_columns: string[];
    searchable_columns: string[];
    detail_columns: string[];
  };
  events: Record<string, { label: string; color: string }>;
}

export interface SourceRecord {
  id: number;
  [key: string]: unknown;
}

interface Status {
  episode_count: number;
  playbook_count: number;
  routine_count: number;
  capture_alive: boolean;
}

export interface PipelineLog {
  id: number;
  stage: string;
  prompt: string;
  response: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  created_at: string;
}

export function qs(params: Record<string, string | number>): string {
  return Object.entries(params)
    .filter(([, v]) => typeof v === "number" || v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join("&");
}

export const api = {
  status: () => get<Status>("/engine/status"),
  episodes: (limit = 20, offset = 0, search = "") =>
    get<{ episodes: Episode[]; total: number }>(`/memory/episodes/?${qs({ limit, offset, search })}`),
  playbooks: (search = "") =>
    get<{ playbooks: Playbook[] }>(`/memory/playbooks/?${qs({ search })}`),
  usage: (days = 30) => get<UsageSummary>(`/engine/usage?days=${days}`),
  budget: () => get<{ daily_spend_usd: number; daily_cap_usd: number; under_budget: boolean }>("/engine/budget"),
  setBudget: (cap: number) => put<{ daily_cap_usd: number }>("/engine/budget", { daily_cap_usd: cap }),
  logs: (limit = 20, offset = 0, search = "", stage = "") =>
    get<{ logs: PipelineLog[]; total: number }>(`/engine/logs?${qs({ limit, offset, search, stage })}`),
  routines: (search = "") =>
    get<{ routines: Routine[] }>(`/memory/routines/?${qs({ search })}`),
  distill: () => post<{ playbook_entries_updated: number }>("/engine/distill"),
  compose: () => post<{ routines_updated: number }>("/engine/routines"),
  gc: () => post<{ status: string }>("/engine/gc"),
  gcStatus: () => get<{ disabled: boolean }>("/engine/gc/status"),
  gcDisable: () => post<{ disabled: boolean }>("/engine/gc/disable"),
  gcEnable: () => post<{ disabled: boolean }>("/engine/gc/enable"),
  insights: (limit = 50, offset = 0) =>
    get<{ insights: Insight[]; total: number }>(`/memory/insights/?${qs({ limit, offset })}`),
  daGoals: () => get<{ goals: DaGoal[] }>("/memory/da-goals/"),
  triggerDa: () => post<{ insights_created: number }>("/engine/da"),
  scmTasks: (status = "") =>
    get<{ tasks: ScmTask[]; total: number }>(`/memory/scm-tasks/?${qs({ status })}`),
  triggerScm: () => post<{ tasks_count: number }>("/engine/scm"),
  updateScmTask: (taskId: number, status: string) =>
    put<{ id: number; status: string }>(`/memory/scm-tasks/${taskId}`, { status }),
  getPrompt: (key: string) =>
    get<{ key: string; prompt: string; is_custom: boolean; default: string }>(`/engine/prompts/${key}`),
  setPrompt: (key: string, prompt: string) =>
    put<{ key: string; saved: boolean }>(`/engine/prompts/${key}`, { prompt }),
  resetPrompt: (key: string) =>
    del_<{ key: string; reset: boolean }>(`/engine/prompts/${key}`),
  sources: () => get<{ sources: SourceManifest[] }>("/engine/sources"),
  sourceData: (name: string, limit = 50, offset = 0, search = "") =>
    get<{ records: SourceRecord[]; total: number }>(
      `/sources/${name}/data?${qs({ limit, offset, search })}`
    ),
  batchDelete: (table: string, ids: number[]) =>
    post<{ deleted: number }>("/batch/delete", { table, ids }),
  updatePlaybook: (fields: Record<string, unknown>) =>
    post<{ updated: boolean }>("/batch/update-playbook", fields),
  pipeline: () => get<{ paused: boolean }>("/engine/pipeline"),
  pipelinePause: () => post<{ paused: boolean }>("/engine/pipeline/pause"),
  pipelineResume: () => post<{ paused: boolean }>("/engine/pipeline/resume"),
  chatHistory: () => get<{ messages: ChatMessage[] }>("/memory/chat/history"),
  chatClear: () => del_("/memory/chat/history"),
  executeProposal: (proposal: Proposal) =>
    post<{ success: boolean; result: Record<string, unknown> }>("/memory/chat/execute-proposal", proposal),
  chatProposalStatus: (messageId: number, proposalIndex: number, status: string) =>
    post<{ updated: boolean }>("/memory/chat/proposal-status", {
      message_id: messageId, proposal_index: proposalIndex, status,
    }),
  chat: async (
    messages: ChatMessage[],
    onToolCall: (name: string, label: string) => void,
    signal?: AbortSignal,
  ): Promise<ChatResult> => {
    const res = await fetch(`${BASE}/memory/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
      signal,
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const reader = res.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const eventMatch = part.match(/^event: (\w+)/m);
        const dataMatch = part.match(/^data: (.+)/m);
        if (!eventMatch || !dataMatch) continue;
        const [event, data] = [eventMatch[1], JSON.parse(dataMatch[1])];
        if (event === "tool_call") onToolCall(data.name, data.label);
        else if (event === "text") return {
          reply: data.content, proposals: data.proposals || [],
          input_tokens: data.input_tokens || 0, output_tokens: data.output_tokens || 0,
        };
        else if (event === "error") throw new Error(data.message);
      }
    }
    throw new Error("Stream ended without response");
  },
};

export interface ChatMessage {
  id?: number;
  role: "user" | "assistant";
  content: string;
  proposals?: string;
}

export interface Proposal {
  type: "delete" | "update_playbook";
  table?: string;
  ids?: number[];
  fields?: Record<string, unknown>;
  reason: string;
}

interface ChatResult {
  reply: string;
  proposals: Proposal[];
  input_tokens: number;
  output_tokens: number;
}

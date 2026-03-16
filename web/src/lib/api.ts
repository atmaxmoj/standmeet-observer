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

export interface Frame {
  id: number;
  timestamp: string;
  app_name: string;
  window_name: string;
  text: string;
  display_id: number;
  image_hash: string;
  image_path: string;
}

export function frameImageUrl(frameId: number): string {
  return `${BASE}/capture/frames/${frameId}/image`;
}

export interface AudioFrame {
  id: number;
  timestamp: string;
  duration_seconds: number;
  text: string;
  language: string;
  source: "mic" | "speaker";
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

export interface OsEvent {
  id: number;
  timestamp: string;
  event_type: string;
  source: string;
  data: string;
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

interface Status {
  episode_count: number;
  playbook_count: number;
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

function qs(params: Record<string, string | number>): string {
  return Object.entries(params)
    .filter(([, v]) => typeof v === "number" || v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join("&");
}

export const api = {
  status: () => get<Status>("/engine/status"),
  frames: (limit = 30, offset = 0, search = "") =>
    get<{ frames: Frame[]; total: number }>(`/capture/frames?${qs({ limit, offset, search })}`),
  audio: (limit = 30, offset = 0, search = "") =>
    get<{ audio: AudioFrame[]; total: number }>(`/capture/audio?${qs({ limit, offset, search })}`),
  episodes: (limit = 20, offset = 0, search = "") =>
    get<{ episodes: Episode[]; total: number }>(`/memory/episodes/?${qs({ limit, offset, search })}`),
  playbooks: (search = "") =>
    get<{ playbooks: Playbook[] }>(`/memory/playbooks/?${qs({ search })}`),
  osEvents: (limit = 50, offset = 0, eventType = "", search = "") =>
    get<{ events: OsEvent[]; total: number }>(
      `/capture/os-events?${qs({ limit, offset, event_type: eventType, search })}`
    ),
  usage: (days = 30) => get<UsageSummary>(`/engine/usage?days=${days}`),
  logs: (limit = 20, offset = 0, search = "") =>
    get<{ logs: PipelineLog[]; total: number }>(`/engine/logs?${qs({ limit, offset, search })}`),
  routines: (search = "") =>
    get<{ routines: Routine[] }>(`/memory/routines/?${qs({ search })}`),
  distill: () => post<{ playbook_entries_updated: number }>("/engine/distill"),
  batchDelete: (table: string, ids: number[]) =>
    post<{ deleted: number }>("/batch/delete", { table, ids }),
  updatePlaybook: (fields: Record<string, unknown>) =>
    post<{ updated: boolean }>("/batch/update-playbook", fields),
  pipeline: () => get<{ paused: boolean }>("/engine/pipeline"),
  pipelinePause: () => post<{ paused: boolean }>("/engine/pipeline/pause"),
  pipelineResume: () => post<{ paused: boolean }>("/engine/pipeline/resume"),
  chatHistory: () => get<{ messages: ChatMessage[] }>("/memory/chat/history"),
  chatClear: () => del_("/memory/chat/history"),
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

const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "POST" });
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

export interface Status {
  episode_count: number;
  playbook_count: number;
}

export const api = {
  status: () => get<Status>("/engine/status"),
  frames: (limit = 30, offset = 0) =>
    get<{ frames: Frame[]; total: number }>(`/capture/frames?limit=${limit}&offset=${offset}`),
  audio: (limit = 30, offset = 0) =>
    get<{ audio: AudioFrame[]; total: number }>(`/capture/audio?limit=${limit}&offset=${offset}`),
  episodes: (limit = 20, offset = 0) =>
    get<{ episodes: Episode[]; total: number }>(`/memory/episodes/?limit=${limit}&offset=${offset}`),
  playbooks: () => get<{ playbooks: Playbook[] }>("/memory/playbooks/"),
  usage: (days = 30) => get<UsageSummary>(`/engine/usage?days=${days}`),
  distill: () => post<{ playbook_entries_updated: number }>("/engine/distill"),
};

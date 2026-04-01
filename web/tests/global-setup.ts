/**
 * Playwright global setup: wait for engine API, seed data, run pipeline.
 *
 * Walks the full production path:
 *   ingest frames → backfill → episode extraction (Haiku) → distill (Opus)
 *
 * Requires real ANTHROPIC_API_KEY. Costs ~$0.02-0.05 per run.
 */

const API = process.env.VITE_API_TARGET || "http://engine-test:5000";

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

async function get(path: string) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`GET ${path}: ${res.status} ${await res.text()}`);
  return res.json();
}

async function post(path: string, body?: unknown) {
  const opts: RequestInit = { method: "POST" };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${API}${path}`, opts);
  if (!res.ok) throw new Error(`POST ${path}: ${res.status} ${await res.text()}`);
  return res.json();
}

async function waitForHealthy(timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${API}/engine/status`);
      if (res.ok) return;
    } catch { /* engine not ready yet */ }
    await sleep(1000);
  }
  throw new Error(`Timed out waiting for engine at ${API}`);
}

async function waitFor(
  label: string,
  check: () => Promise<boolean>,
  timeoutMs = 120000,
) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await check()) return;
    await sleep(2000);
  }
  throw new Error(`Timed out waiting for: ${label}`);
}

async function seedFrames() {
  // Seed screen frames with time gaps to create windows.
  // Group 1: 20 frames, ~40 minutes ago (will form a complete window)
  // Group 2: 15 frames, now (current activity)
  const now = Date.now();
  const fortyMinAgo = now - 40 * 60 * 1000;

  for (let i = 0; i < 20; i++) {
    const ts = new Date(fortyMinAgo + i * 60_000).toISOString(); // 1 frame/min
    await post("/ingest/screen", {
      timestamp: ts,
      app_name: "VSCode",
      window_name: `editor.py - Project ${i % 3}`,
      text: `Writing unit tests for the authentication module, checking edge cases for token refresh flow iteration ${i}`,
      display_id: 1,
    });
  }

  // 10 minute idle gap (no frames) — triggers window boundary

  for (let i = 0; i < 15; i++) {
    const ts = new Date(now - (15 - i) * 60_000).toISOString();
    await post("/ingest/screen", {
      timestamp: ts,
      app_name: "Terminal",
      window_name: "zsh",
      text: `Running pytest, reviewing test output, fixing assertion errors in test_auth.py iteration ${i}`,
      display_id: 1,
    });
  }

  // Also seed some other source types
  await post("/ingest/zsh", {
    timestamp: new Date(fortyMinAgo).toISOString(),
    command: "pytest tests/test_auth.py -v",
  });

  await post("/ingest/chrome", {
    timestamp: new Date(fortyMinAgo + 5 * 60_000).toISOString(),
    url: "https://docs.python.org/3/library/unittest.mock.html",
  });
}

export default async function globalSetup() {
  console.log("[test] Waiting for engine API...");
  await waitForHealthy();
  console.log("[test] Engine ready");

  console.log("[test] Seeding frames...");
  await seedFrames();
  console.log("[test] Frames seeded (35 screen + zsh + chrome)");

  console.log("[test] Running backfill...");
  const bf = await post("/engine/backfill");
  console.log(`[test] Backfill: ${bf.windows} windows from ${bf.total_frames} frames`);

  console.log("[test] Waiting for episodes...");
  await waitFor("episodes", async () => {
    const data = await get("/memory/episodes/?limit=1");
    return data.total > 0;
  });
  const epData = await get("/memory/episodes/?limit=1");
  console.log(`[test] Episodes ready: ${epData.total} episodes`);

  console.log("[test] Running distill...");
  const distill = await post("/engine/distill");
  console.log(`[test] Distill: ${distill.playbook_entries_updated} entries`);

  console.log("[test] Waiting for playbooks...");
  await waitFor("playbooks", async () => {
    const data = await get("/memory/playbooks/");
    return data.playbooks.length > 0;
  });
  const pbData = await get("/memory/playbooks/");
  console.log(`[test] Playbooks ready: ${pbData.playbooks.length} entries`);

  console.log("[test] Setup complete");
}

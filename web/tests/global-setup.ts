/**
 * Playwright global setup: wait for engine API, then seed test data.
 *
 * Docker containers are started by docker-compose.test.yml (via npm test),
 * not by this script.
 */

const API = process.env.VITE_API_TARGET || "http://engine-test:5000";

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitForHealthy(url: string, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${url}/engine/status`);
      if (res.ok) return;
    } catch {}
    await sleep(1000);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function post(path: string, body: unknown) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Seed failed: ${res.status} ${await res.text()}`);
  return res.json();
}

async function seedTestData() {
  const now = new Date().toISOString();

  for (let i = 0; i < 35; i++) {
    await post("/ingest/frame", {
      timestamp: now,
      app_name: `TestApp${i}`,
      window_name: `Test Window ${i}`,
      text: `Test frame content number ${i} with some searchable text`,
      display_id: 1,
    });
  }

  await post("/ingest/audio", {
    timestamp: now,
    text: "Test audio transcription content",
    language: "en",
    duration_seconds: 10.0,
    source: "mic",
  });

  await post("/ingest/os-event", {
    timestamp: now,
    event_type: "shell_command",
    source: "zsh",
    data: "echo hello world",
  });
  await post("/ingest/os-event", {
    timestamp: now,
    event_type: "browser_url",
    source: "chrome",
    data: "https://example.com",
  });
}

export default async function globalSetup() {
  console.log("[test] Waiting for engine API...");
  await waitForHealthy(API);
  console.log("[test] Engine ready");

  console.log("[test] Seeding test data...");
  await seedTestData();
  console.log("[test] Seed complete");
}

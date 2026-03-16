import { execSync } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "../..");
const COMPOSE_FILE = path.join(ROOT, "docker-compose.test.yml");
const API = "http://localhost:5002";

function waitForHealthy(url: string, timeoutMs = 30000): Promise<void> {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      try {
        execSync(`curl -sf ${url}`, { stdio: "ignore" });
        resolve();
      } catch {
        if (Date.now() - start > timeoutMs) {
          reject(new Error(`Timed out waiting for ${url}`));
        } else {
          setTimeout(check, 1000);
        }
      }
    };
    check();
  });
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

  // Seed frames (>30 to trigger pagination)
  for (let i = 0; i < 35; i++) {
    await post("/ingest/frame", {
      timestamp: now,
      app_name: `TestApp${i}`,
      window_name: `Test Window ${i}`,
      text: `Test frame content number ${i} with some searchable text`,
      display_id: 1,
    });
  }

  // Seed audio
  await post("/ingest/audio", {
    timestamp: now,
    text: "Test audio transcription content",
    language: "en",
    duration_seconds: 10.0,
    source: "mic",
  });

  // Seed OS events
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
  console.log("[test] Starting test backend container...");
  execSync(`docker compose -p bisimulator-test -f ${COMPOSE_FILE} up -d --build --wait`, {
    cwd: ROOT,
    stdio: "inherit",
  });
  await waitForHealthy(`${API}/engine/status`);
  console.log("[test] Backend ready on :5002");

  console.log("[test] Seeding test data...");
  await seedTestData();
  console.log("[test] Seed complete");
}

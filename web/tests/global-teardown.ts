import { execSync } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "../..");
const COMPOSE_FILE = path.join(ROOT, "docker-compose.test.yml");

export default async function globalTeardown() {
  console.log("[test] Stopping test backend container...");
  execSync(`docker compose -p bisimulator-test -f ${COMPOSE_FILE} down -v`, {
    cwd: ROOT,
    stdio: "inherit",
  });
  console.log("[test] Test containers cleaned up");
}

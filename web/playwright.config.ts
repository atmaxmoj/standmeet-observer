import { defineConfig } from "@playwright/test";

const baseURL = process.env.PW_BASE_URL || "http://localhost:5173";
const apiURL = process.env.VITE_API_TARGET || "http://localhost:5001";

export default defineConfig({
  testDir: "./tests",
  timeout: 420000,
  globalSetup: "./tests/global-setup.ts",
  use: {
    baseURL,
    screenshot: "on",
  },
  // No webServer — Vite is started by docker-compose or the developer
});

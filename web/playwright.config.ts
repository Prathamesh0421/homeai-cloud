/**
 * Playwright E2E specs (docs/05 §6) against a running, seeded stack — not part of CI.
 *
 *   npx playwright install chromium          # once
 *   E2E_BASE_URL=http://44.226.166.194 npm run e2e
 *   E2E_VIDEO=1 ...                          # record every test (demo preview)
 *
 * One worker: the specs share the stack's data (Maple St, its alerts and rules).
 */
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: process.env.E2E_VIDEO ? "on" : "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});

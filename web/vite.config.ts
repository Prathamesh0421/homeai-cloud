/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Without the Caddy gateway: each component's paths go to its own port (01 routing table).
      // Longest prefixes first; the rest of /api stays with C4.
      // UI-only against live EC2 (no local Docker): set both targets to http://44.226.166.194
      // C4 owns these house sub-resources; regex keys must come before the C1 "/api/v1/houses" prefix.
      "^/api/v1/houses/[^/]+/(settings|emergency-contacts)": "http://localhost:8004",
      "/api/v1/emergency-contacts": "http://localhost:8004",
      "/api/v1/houses": "http://localhost:8001",
      "/api/v1/rooms": "http://localhost:8001",
      "/api/v1/feeds": "http://localhost:8001",
      "/api/v1/ingest": "http://localhost:8001",
      "/api/v1/clips": "http://localhost:8001",
      "/api/v1/alerts": "http://localhost:8002",
      "/api/v1/alert-rules": "http://localhost:8002",
      "/api/v1/alert-types": "http://localhost:8002",
      "/api/v1/alert-view": "http://localhost:8002",
      "/api/v1/records": "http://localhost:8003",
      "/api/v1/detections": "http://localhost:8003",
      "/api/v1/activity-patterns": "http://localhost:8003",
      "/api/v1/models": "http://localhost:8003",
      "/api/v1/inference": "http://localhost:8003",
      "/api/v1/data-dictionary": "http://localhost:8003",
      "/api/v1/integrity-checks": "http://localhost:8003",
      "/api/v1/integrity-reports": "http://localhost:8003",
      "/api/v1/media-events": "http://localhost:8003",
      "/api": "http://localhost:8004",
      "/.well-known": "http://localhost:8004",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
  },
});

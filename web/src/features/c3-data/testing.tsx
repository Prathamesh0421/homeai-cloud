/** Test harness for the C3 pages: session, QueryClient, toasts, router, and a fetch stub. */

import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { AuthProvider } from "../../auth/AuthProvider";
import { ToastProvider, ToastViewport } from "../../shared/Toasts";
import type {
  ActivityPattern,
  DeploymentStatus,
  IntegrityReport,
  ModelDetail,
  ModelSummary,
  TestClassifyResult,
} from "../../api/c3";

export const HOUSE = "22222222-0000-0000-0000-0000000000a1";
export const TENANT = "11111111-0000-0000-0000-000000000001";

export function signIn(role: "house_owner" | "cloud_staff" = "cloud_staff") {
  const claims = {
    sub: "44444444-0000-0000-0000-000000000002",
    role,
    tenant_id: role === "cloud_staff" ? null : TENANT,
    house_ids: role === "cloud_staff" ? [] : [HOUSE],
    email: "ops@acme.test",
    jti: "j1",
  };
  sessionStorage.setItem("homeai.token", `h.${btoa(JSON.stringify(claims))}.s`);
}

type ReplyBody = { status?: number; body?: unknown; headers?: Record<string, string>; raw?: string };
type Reply = ReplyBody | ((init: RequestInit) => ReplyBody);

/** ``stubFetch({"GET /api/v1/models": {...}})``: matched on method + path prefix (query ignored). */
export function stubFetch(routes: Record<string, Reply>) {
  const calls: { method: string; url: string; body: unknown; headers: Record<string, string> }[] = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const path = url.split("?")[0];
    let body: unknown;
    if (init.body instanceof FormData) body = "<form-data>";
    else if (init.body) {
      try {
        body = JSON.parse(String(init.body));
      } catch {
        body = String(init.body);
      }
    }
    calls.push({ method, url, body, headers: (init.headers ?? {}) as Record<string, string> });
    const key = Object.keys(routes).find(
      (k) => k.startsWith(`${method} `) && path === k.slice(method.length + 1),
    );
    const reply = key ? routes[key] : { status: 404, body: { error: { code: "not_found", message: "no stub" } } };
    const { status = 200, body: rbody, headers, raw } = typeof reply === "function" ? reply(init) : reply;
    const text = raw ?? (rbody === undefined ? "" : JSON.stringify(rbody));
    return new Response(text, { status, headers });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function renderPage(path: string, page: ReactElement, route: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route path={route} element={page} />
              <Route path="/ops/models/:modelId" element={<div data-testid="model-detail-route" />} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
        <ToastViewport />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { ...view, client };
}

export function page<T>(rows: T[], total = rows.length) {
  return { data: rows, meta: { page: 1, page_size: 25, total } };
}

export function model(overrides: Partial<ModelSummary> = {}): ModelSummary {
  return {
    model_id: "m0000000-0000-4000-8000-000000000001",
    name: "yamnet",
    version: "1.0.0",
    status: "active",
    source: "bundled",
    metrics: { accuracy: 0.91 },
    created_at: "2026-06-01T12:00:00Z",
    activated_at: "2026-06-01T12:05:00Z",
    ...overrides,
  };
}

export function modelDetail(overrides: Partial<ModelDetail> = {}): ModelDetail {
  return {
    ...model(),
    label_map: {
      version: "1.0.0",
      entries: [
        {
          home_label: "glass_break",
          category: "security",
          source_classes: ["Glass", "Shatter"],
          min_confidence: 0.5,
          rule: "max",
        },
      ],
    },
    notes: "bundled baseline",
    evaluations: [],
    ...overrides,
  };
}

export function deployment(overrides: Partial<DeploymentStatus> = {}): DeploymentStatus {
  return {
    active_model: { model_id: "m1", name: "yamnet", version: "1.0.0" },
    workers: [
      {
        worker_id: "host-1",
        hostname: "host",
        model_id: "m1",
        model_version: "1.0.0",
        last_heartbeat: new Date().toISOString(),
        processed: 10,
        failed: 0,
        avg_latency_ms: 120,
      },
    ],
    queue: { queued: 1, processing: 0, failed: 0, analyzed_last_hour: 9 },
    throughput_per_min: 4.2,
    p95_latency_ms: 180,
    ...overrides,
  };
}

export function classifyResult(overrides: Partial<TestClassifyResult> = {}): TestClassifyResult {
  return {
    model: { model_id: "m1", name: "yamnet", version: "1.0.0" },
    top_label: "glass_break",
    top_confidence: 0.82,
    labels: [
      { label: "glass_break", confidence: 0.82, source_class: "Glass", start_s: 0, end_s: 1 },
    ],
    raw_top10: [
      { class_name: "Glass", score: 0.82 },
      { class_name: "Shatter", score: 0.4 },
    ],
    frames: 20,
    duration_s: 2.0,
    latency_ms: 140,
    ...overrides,
  };
}

export function integrityReport(overrides: Partial<IntegrityReport> = {}): IntegrityReport {
  return {
    report_id: "r0000000-0000-4000-8000-000000000001",
    scope: { tenant_id: null },
    status: "done",
    findings: [
      { kind: "analyzed_no_detection", severity: "high", entity_id: "m-1", detail: {} },
      { kind: "handoff_pending", severity: "medium", entity_id: "m-2", detail: {} },
    ],
    started_at: "2026-06-01T03:00:00Z",
    finished_at: "2026-06-01T03:00:05Z",
    ...overrides,
  };
}

export function activity(overrides: Partial<ActivityPattern> = {}): ActivityPattern {
  const hours = Array(24).fill(0);
  hours[14] = 3;
  return {
    house_id: HOUSE,
    room_id: "33333333-0000-0000-0000-00000000a101",
    date: "2026-06-01",
    hours,
    baseline_mean: Array(24).fill(1),
    baseline_std: Array(24).fill(0.5),
    anomaly_score: 0.2,
    band: "normal",
    last_activity_at: "2026-06-01T14:30:00Z",
    ...overrides,
  };
}

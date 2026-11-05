/** Test harness for the C2 pages: session, QueryClient, toasts, router, and a fetch stub. */

import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { AuthProvider } from "../../auth/AuthProvider";
import { ToastProvider, ToastViewport } from "../../shared/Toasts";
import type { AlertDetail, AlertSummary } from "../../api/c2";

export const HOUSE = "22222222-0000-0000-0000-0000000000a1";

export function signIn(role: "house_owner" | "cloud_staff" = "house_owner") {
  const claims = {
    sub: "44444444-0000-0000-0000-000000000002",
    role,
    tenant_id: role === "cloud_staff" ? null : "11111111-0000-0000-0000-000000000001",
    house_ids: role === "cloud_staff" ? [] : [HOUSE],
    email: "owner.maple@acme.test",
    jti: "j1",
  };
  sessionStorage.setItem("homeai.token", `h.${btoa(JSON.stringify(claims))}.s`);
}

type Reply = { status?: number; body?: unknown } | ((init: RequestInit) => { status?: number; body?: unknown });

/** ``stubFetch({"GET /api/v1/alerts": {...}})``: matched on method + path prefix (query ignored). */
export function stubFetch(routes: Record<string, Reply>) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const path = url.split("?")[0];
    calls.push({ method, url, body: init.body ? JSON.parse(String(init.body)) : undefined });
    const key = Object.keys(routes).find(
      (k) => k.startsWith(`${method} `) && path === k.slice(method.length + 1),
    );
    const reply = key ? routes[key] : { status: 404, body: { error: { code: "not_found", message: "no stub" } } };
    const { status = 200, body } = typeof reply === "function" ? reply(init) : reply;
    return new Response(body === undefined ? "" : JSON.stringify(body), { status });
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
              <Route path="/alerts/:alertId" element={<div data-testid="detail-route" />} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
        <ToastViewport />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { ...view, client };
}

export function summary(overrides: Partial<AlertSummary> = {}): AlertSummary {
  return {
    alert_id: "a0000000-0000-4000-8000-000000000001",
    tenant_id: "11111111-0000-0000-0000-000000000001",
    house_id: HOUSE,
    house_name: "Maple St",
    room_id: "33333333-0000-0000-0000-00000000a101",
    room_name: "Kitchen",
    alert_type_code: "intrusion",
    alert_type_name: "Possible intrusion",
    category: "security",
    severity: "high",
    status: "open",
    top_label: "glass_break",
    top_confidence: 0.78,
    triggered_at: new Date(Date.now() - 2 * 60_000).toISOString(),
    ...overrides,
  };
}

export function detail(overrides: Partial<AlertDetail> = {}): AlertDetail {
  return {
    ...summary(),
    rule_id: "r1",
    detection_id: "d1",
    media_id: "m1",
    acknowledged_at: null,
    resolved_at: null,
    updated_at: new Date().toISOString(),
    allowed_actions: ["acknowledge", "false_positive"],
    evidence: {
      detection_id: "d1",
      media_id: "m1",
      labels: [
        { label: "glass_break", confidence: 0.78 },
        { label: "speech", confidence: 0.12 },
      ],
      model: { model_id: "mod1", name: "yamnet", version: "1.0.0" },
      detection_available: true,
      threshold: 0.55,
    },
    timeline: [
      {
        from_status: null,
        to_status: "open",
        actor_id: "c3-worker",
        actor_role: "service",
        note: null,
        changed_at: new Date().toISOString(),
      },
    ],
    notifications: [
      {
        notification_id: "n0",
        channel: "in_app",
        contact_id: null,
        recipient: null,
        priority: null,
        status: "sent",
        attempt_count: 1,
        last_error: null,
        created_at: new Date().toISOString(),
        sent_at: new Date().toISOString(),
      },
      {
        notification_id: "n1",
        channel: "email",
        contact_id: "c1",
        recipient: "alice.maple@example.test",
        priority: 1,
        status: "failed",
        attempt_count: 1,
        last_error: "subscription_pending",
        created_at: new Date().toISOString(),
        sent_at: null,
      },
    ],
    ...overrides,
  };
}

export function page<T>(rows: T[], total = rows.length) {
  return { data: rows, meta: { page: 1, page_size: 25, total } };
}

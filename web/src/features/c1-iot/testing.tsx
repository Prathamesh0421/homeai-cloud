/** Test harness for the C1 pages: session, QueryClient, toasts, router, and a fetch stub. */

import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { AuthProvider } from "../../auth/AuthProvider";
import { ToastProvider, ToastViewport } from "../../shared/Toasts";
import type { FeedDetail, House } from "../../api/c1";

export const TENANT = "11111111-0000-0000-0000-000000000001";
export const HOUSE = "22222222-0000-0000-0000-0000000000a1";
export const ROOM = "33333333-0000-0000-0000-00000000a101";
export const FEED = "55555555-0000-4000-8000-000000000001";

export function signIn(role: "iot_staff" | "house_owner" | "cloud_staff" = "iot_staff") {
  const claims = {
    sub: "44444444-0000-0000-0000-000000000003",
    role,
    tenant_id: role === "cloud_staff" ? null : TENANT,
    house_ids: role === "house_owner" ? [HOUSE] : [],
    email: "iot@acme.test",
    jti: "j1",
  };
  sessionStorage.setItem("homeai.token", `h.${btoa(JSON.stringify(claims))}.s`);
}

type ReplyBody = { status?: number; body?: unknown };
type Reply = ReplyBody | ((init: RequestInit) => ReplyBody);
export interface Call {
  method: string;
  url: string;
  body: unknown;
}

/** ``stubFetch({"GET /api/v1/feeds": {...}})``: matched on method + exact path (query ignored). */
export function stubFetch(routes: Record<string, Reply>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const path = url.split("?")[0];
    const raw = init.body;
    calls.push({ method, url, body: typeof raw === "string" ? JSON.parse(raw) : raw });
    const reply = routes[`${method} ${path}`] ?? {
      status: 404,
      body: { error: { code: "not_found", message: "no stub" } },
    };
    const { status = 200, body } = typeof reply === "function" ? reply(init) : reply;
    return new Response(body === undefined ? null : JSON.stringify(body), { status });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function renderPage(path: string, page: ReactElement, route: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route path={route} element={page} />
              <Route path="/iot/feeds" element={<div data-testid="feeds-route" />} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
        <ToastViewport />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

export function page<T>(rows: T[], total = rows.length) {
  return { data: rows, meta: { page: 1, page_size: 25, total } };
}

export function house(overrides: Partial<House> = {}): House {
  return {
    house_id: HOUSE,
    tenant_id: TENANT,
    name: "Maple St",
    address: null,
    timezone: "America/Los_Angeles",
    owner_user_id: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    ...overrides,
  };
}

export function feed(overrides: Partial<FeedDetail> = {}): FeedDetail {
  return {
    feed_id: FEED,
    tenant_id: TENANT,
    house_id: HOUSE,
    house_name: "Maple St",
    room_id: null,
    room_name: null,
    name: "Hall Mic",
    media_kind: "audio",
    status: "provisioned",
    is_enabled: false,
    connectivity_status: "unknown",
    config: { capture_interval_s: 30, sensitivity: "medium", network_label: null },
    config_version: 1,
    last_clip_at: null,
    created_at: "2026-11-10T00:00:00Z",
    archived_at: null,
    recent_clips: [],
    ...overrides,
  };
}

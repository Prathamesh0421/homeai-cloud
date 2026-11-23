/**
 * API helpers for the E2E specs: real tokens from C4, the seeded IDs (scripts/seed_ids.py) and
 * the clip pipeline (C1 ingest -> C3 -> C2), all through the gateway at E2E_BASE_URL.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, type APIRequestContext, type APIResponse, type Page } from "@playwright/test";

export const ACME = "11111111-0000-0000-0000-000000000001";
export const MAPLE = "22222222-0000-0000-0000-0000000000a1";
export const MAPLE_BATHROOM = "33333333-0000-0000-0000-00000000a104";
const MAPLE_KITCHEN_MIC = "66666666-0000-0000-0000-00000000a101";

export const OWNER = "owner.maple@acme.test";
export const OPS = "ops@homeai.test";
const PASSWORD = process.env.DEMO_PASSWORD ?? "Demo!2026";

const CLIENTS = {
  "c3-worker": { scope: ["alerts:evaluate"], secret: process.env.SERVICE_CLIENT_SECRET_C3 ?? "dev-c3-secret" },
  "device-uploader": {
    scope: ["ingest:write"],
    secret: process.env.SERVICE_CLIENT_SECRET_DEVICE ?? "dev-device-secret",
  },
} as const;

const tokens = new Map<string, string>();

async function data<T>(res: APIResponse): Promise<T> {
  if (!res.ok()) throw new Error(`${res.url()} -> ${res.status()}: ${(await res.text()).slice(0, 300)}`);
  return res.status() === 204 ? (undefined as T) : ((await res.json()).data as T);
}

export async function userToken(api: APIRequestContext, email: string): Promise<string> {
  if (!tokens.has(email)) {
    const body = await data<{ token: string }>(
      await api.post("/api/v1/auth/login", { data: { email, password: PASSWORD } }),
    );
    tokens.set(email, body.token);
  }
  return tokens.get(email)!;
}

async function serviceToken(api: APIRequestContext, client: keyof typeof CLIENTS): Promise<string> {
  if (!tokens.has(client)) {
    const { scope, secret } = CLIENTS[client];
    const body = await data<{ token: string }>(
      await api.post("/api/v1/auth/service-token", { data: { client_id: client, client_secret: secret, scope } }),
    );
    tokens.set(client, body.token);
  }
  return tokens.get(client)!;
}

const auth = (token: string) => ({ Authorization: `Bearer ${token}` });

export async function call<T>(
  api: APIRequestContext,
  method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE",
  path: string,
  email: string,
  body?: object,
): Promise<T> {
  const headers = auth(await userToken(api, email));
  return data<T>(await api.fetch(path, { method, headers, data: body }));
}

export interface AlertDetail {
  alert_id: string;
  status: string;
  alert_type_name: string;
  notifications: { channel: string; recipient: string | null; view_link: string | null }[];
}

/**
 * An open alert at Maple St. `E2E_ALERT_ID` reuses one (e.g. from `make demo-c2-detect`);
 * otherwise glass_break.wav goes through the real pipeline and the alert C3's handoff raised is
 * found by sending the stored detection to C2 again (a duplicate answers with its alert id).
 */
export async function raiseAlert(api: APIRequestContext): Promise<string> {
  if (process.env.E2E_ALERT_ID) return process.env.E2E_ALERT_ID;

  const clip = fileURLToPath(new URL("../../demo_clips/glass_break.wav", import.meta.url));
  const ingest = await data<{ media_id: string }>(
    await api.post("/api/v1/ingest/clip", {
      headers: auth(await serviceToken(api, "device-uploader")),
      multipart: {
        feed_id: MAPLE_KITCHEN_MIC,
        media_kind: "audio",
        captured_at: new Date().toISOString(),
        file: { name: "glass_break.wav", mimeType: "audio/wav", buffer: readFileSync(clip) },
      },
    }),
  );

  const owner = await userToken(api, OWNER);
  let event: { status?: string; detection_id?: string; handoff_status?: string } = {};
  await expect
    .poll(
      async () => {
        const res = await api.get(`/api/v1/records/clips/${ingest.media_id}`, { headers: auth(owner) });
        if (res.ok()) event = (await res.json()).data;
        return event.status;
      },
      { message: "C3 analyses the clip", timeout: 90_000, intervals: [2_000] },
    )
    .toBe("analyzed");
  expect(event.handoff_status, "C3 handed the detection to C2 (HANDOFF_MODE=call)").toBe("done");

  const d = await data<Record<string, unknown>>(
    await api.get(`/api/v1/records/detections/${event.detection_id}`, { headers: auth(owner) }),
  );
  const decision = await data<{ decision: string; alert_id: string; duplicate: boolean }>(
    await api.post("/api/v1/alerts/evaluate", {
      headers: auth(await serviceToken(api, "c3-worker")),
      data: {
        detection_id: d.id,
        media_id: d.media_id,
        house_id: d.house_id,
        room_id: d.room_id,
        top_label: d.top_label,
        top_confidence: d.top_confidence,
        labels: d.labels,
        detected_at: d.detected_at,
      },
    }),
  );
  expect(decision, `glass_break.wav raised an alert (${d.top_label} ${d.top_confidence})`).toMatchObject({
    decision: "alert",
    duplicate: true,
  });
  return decision.alert_id;
}

/** Leaves the stack as found: acknowledges and resolves the alert if it is still open. */
export async function closeAlert(api: APIRequestContext, alertId: string): Promise<void> {
  const a = await call<AlertDetail>(api, "GET", `/api/v1/alerts/${alertId}`, OWNER);
  if (a.status === "open") await call(api, "POST", `/api/v1/alerts/${alertId}/acknowledge`, OWNER, {});
  if (a.status === "open" || a.status === "acknowledged") {
    await call(api, "POST", `/api/v1/alerts/${alertId}/resolve`, OWNER, {});
  }
}

export async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

/** C3-15..18: api/c3.ts, format helpers, and the seven C3 UI pages. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { detectionsStats, listModels, recordsQuery } from "../../api/c3";
import ModelsPage from "./ModelsPage";
import ModelDetailPage from "./ModelDetailPage";
import ClassifyPage from "./ClassifyPage";
import RecordsPage from "./RecordsPage";
import DictionaryPage from "./DictionaryPage";
import IntegrityPage from "./IntegrityPage";
import ActivityPage from "./ActivityPage";
import {
  HOUSE,
  TENANT,
  activity,
  classifyResult,
  deployment,
  integrityReport,
  model,
  modelDetail,
  page,
  renderPage,
  signIn,
  stubFetch,
} from "./testing";
import { BAND_LABEL, utcHourLabel, workerIsStale } from "./format";

beforeEach(() => {
  sessionStorage.clear();
  signIn();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// --- format + client ------------------------------------------------------------------------

describe("format", () => {
  it("labels a UTC hour with the UTC suffix (no local conversion)", () => {
    expect(utcHourLabel(0)).toBe("00:00 UTC");
    expect(utcHourLabel(14)).toBe("14:00 UTC");
  });

  it("calls a worker stale past ~2 intervals", () => {
    const now = new Date("2026-06-01T12:00:00Z");
    expect(workerIsStale("2026-06-01T11:59:30Z", now)).toBe(false);
    expect(workerIsStale("2026-06-01T11:55:00Z", now)).toBe(true);
    expect(workerIsStale(null, now)).toBe(true);
  });

  it("maps insufficient_data to a 'collecting data' label", () => {
    expect(BAND_LABEL.insufficient_data).toBe("Collecting data");
  });
});

describe("api/c3", () => {
  it("builds the records query", () => {
    expect(recordsQuery({ tenantId: "t1", houseId: HOUSE, filter: "top_label:dog", page: 2 })).toBe(
      `tenant_id=t1&house_id=${HOUSE}&filter=top_label%3Adog&page=2&page_size=25`,
    );
  });

  it("unwraps a models list and stats", async () => {
    stubFetch({
      "GET /api/v1/models": { body: { data: [model(), model({ model_id: "m2", version: "1.1.0", status: "registered" })] } },
      "GET /api/v1/detections/stats": { body: { data: [{ key: "dog", count: 3 }] } },
    });
    expect((await listModels()).length).toBe(2);
    expect((await detectionsStats({ groupBy: "top_label" }))[0]).toEqual({ key: "dog", count: 3 });
  });
});

// --- Models ---------------------------------------------------------------------------------

describe("ModelsPage", () => {
  function renderModels() {
    return renderPage("/ops/models", <ModelsPage />, "/ops/models");
  }

  it("lists versions with deployment KPIs", async () => {
    stubFetch({
      "GET /api/v1/models": { body: { data: [model(), model({ model_id: "m2", version: "1.1.0", status: "registered" })] } },
      "GET /api/v1/models/deployment": { body: { data: deployment() } },
    });
    renderModels();
    expect(await screen.findByText("yamnet 1.0.0")).toBeInTheDocument();
    expect(screen.getByText("yamnet 1.1.0")).toBeInTheDocument();
    // 1 worker, fresh heartbeat -> 1 live, "all healthy" (unique hint text).
    expect(screen.getByText("all healthy")).toBeInTheDocument();
  });

  it("opens a version detail on click", async () => {
    stubFetch({
      "GET /api/v1/models": { body: { data: [model()] } },
      "GET /api/v1/models/deployment": { body: { data: deployment() } },
    });
    renderModels();
    fireEvent.click(await screen.findByText("yamnet 1.0.0"));
    expect(await screen.findByTestId("model-detail-route")).toBeInTheDocument();
  });

  it("creates a new version", async () => {
    const { calls } = stubFetch({
      "GET /api/v1/models": { body: { data: [model()] } },
      "GET /api/v1/models/deployment": { body: { data: deployment() } },
      "POST /api/v1/models": { body: { data: modelDetail({ model_id: "m9", version: "2.0.0", status: "registered" }) } },
    });
    renderModels();
    fireEvent.click(await screen.findByRole("button", { name: "New version" }));
    fireEvent.change(screen.getByPlaceholderText("e.g. 1.1.0"), { target: { value: "2.0.0" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")).toBeTruthy());
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ version: "2.0.0" });
  });
});

// --- Model Detail ---------------------------------------------------------------------------

describe("ModelDetailPage", () => {
  function renderDetail() {
    return renderPage("/ops/models/m1", <ModelDetailPage />, "/ops/models/:modelId");
  }

  it("shows the label map and disables Activate for the active model", async () => {
    stubFetch({ "GET /api/v1/models/m1": { body: { data: modelDetail({ status: "active" }) } } });
    renderDetail();
    expect(await screen.findByText("Glass break")).toBeInTheDocument(); // home label row
    expect(screen.getByText("Glass, Shatter")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Active" })).toBeDisabled();
  });

  it("activates a non-active version", async () => {
    const { calls } = stubFetch({
      "GET /api/v1/models/m1": { body: { data: modelDetail({ status: "evaluated" }) } },
      "POST /api/v1/models/m1/activate": { body: { data: modelDetail({ status: "active" }) } },
    });
    renderDetail();
    fireEvent.click(await screen.findByRole("button", { name: "Activate" }));
    await waitFor(() => expect(calls.find((c) => c.url.endsWith("/activate"))).toBeTruthy());
    expect(await screen.findByText("Model activated")).toBeInTheDocument();
  });
});

// --- Test Classify --------------------------------------------------------------------------

describe("ClassifyPage", () => {
  function renderClassify() {
    return renderPage("/ops/classify", <ClassifyPage />, "/ops/classify");
  }

  it("uploads a clip and shows labels + raw scores + latency", async () => {
    stubFetch({ "POST /api/v1/inference/test": { body: { data: classifyResult() } } });
    renderClassify();
    const file = new File([new Uint8Array([1, 2, 3])], "clip.wav", { type: "audio/wav" });
    fireEvent.change(screen.getByLabelText("Clip file"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Classify" }));
    // "Glass break" shows both as the top-label metric and as a home-label bar; "82%" likewise.
    expect((await screen.findAllByText("Glass break")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("82%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("140 ms")).toBeInTheDocument(); // latency metric (unique)
    expect(screen.getByText("Glass")).toBeInTheDocument(); // raw YAMNet class
  });
});

// --- Records --------------------------------------------------------------------------------

describe("RecordsPage", () => {
  function renderRecords(path = "/ops/records") {
    return renderPage(path, <RecordsPage />, "/ops/records");
  }

  it("shows a scope note and lists detections, switching entity", async () => {
    const { calls } = stubFetch({
      "GET /api/v1/records/detections": {
        body: page([{ id: "d1", top_label: "dog", top_confidence: 0.6, house_id: HOUSE, detected_at: "2026-06-01T10:00:00Z" }]),
      },
      "GET /api/v1/records/houses": { body: page([{ house_id: "h1", name: "Maple", tenant_id: "t1" }]) },
    });
    renderRecords();
    expect(await screen.findByText("dog")).toBeInTheDocument();
    expect(screen.getByText(/Cloud staff: all tenants/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "houses" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/records/houses"))).toBe(true));
    expect(await screen.findByText("Maple")).toBeInTheDocument();
  });

  it("opens the row drawer with the full JSON", async () => {
    stubFetch({
      "GET /api/v1/records/detections": { body: page([{ id: "d1", top_label: "dog", top_confidence: 0.6, house_id: HOUSE }]) },
    });
    renderRecords();
    fireEvent.click(await screen.findByText("dog"));
    const drawer = await screen.findByRole("dialog", { name: "Record detail" });
    expect(within(drawer).getByText(/"top_label": "dog"/)).toBeInTheDocument();
  });

  it("surfaces a 429 rate-limit message", async () => {
    stubFetch({
      "GET /api/v1/records/detections": { status: 429, body: { error: { code: "rate_limited", message: "slow down" } } },
    });
    renderRecords();
    expect(await screen.findByText(/Too many requests/)).toBeInTheDocument();
  });
});

// --- Data Dictionary ------------------------------------------------------------------------

describe("DictionaryPage", () => {
  const GROUPED = {
    data: {
      version: "v1",
      generated_at: "2026-06-01T00:00:00Z",
      components: [
        {
          component: "c3",
          entities: [
            {
              name: "activity_patterns",
              store: "mongo",
              schema_name: null,
              owner_component: "c3",
              fields: [
                { name: "hours", type: "array<int>[24]", nullable: null, internal: false, description: "per-hour counts" },
                { name: "counted", type: "array", nullable: null, internal: true, description: "internal ledger" },
              ],
            },
          ],
        },
      ],
    },
  };

  function renderDict() {
    return renderPage("/ops/dictionary", <DictionaryPage />, "/ops/dictionary");
  }

  it("shows entities grouped by component and marks internal fields", async () => {
    stubFetch({
      "GET /api/v1/data-dictionary": { body: GROUPED },
      "GET /api/v1/data-dictionary/versions": { body: { data: [{ version: "v1", published_by: "u", published_at: "2026-06-01T00:00:00Z" }] } },
    });
    renderDict();
    expect(await screen.findByText("activity_patterns")).toBeInTheDocument();
    const countedRow = screen.getByText("counted").closest("tr")!;
    expect(within(countedRow).getByText("internal")).toBeInTheDocument();
  });

  it("generates a new version", async () => {
    const { calls } = stubFetch({
      "GET /api/v1/data-dictionary": { body: GROUPED },
      "GET /api/v1/data-dictionary/versions": { body: { data: [] } },
      "POST /api/v1/data-dictionary": { body: { data: { version: "v2", entities: 12 } } },
    });
    renderDict();
    await screen.findByText("activity_patterns");
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")).toBeTruthy());
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ generate: true });
  });

  it("shows the empty state when no dictionary exists (404)", async () => {
    stubFetch({
      "GET /api/v1/data-dictionary": { status: 404, body: { error: { code: "not_found", message: "none" } } },
      "GET /api/v1/data-dictionary/versions": { body: { data: [] } },
    });
    renderDict();
    expect(await screen.findByText("No dictionary yet")).toBeInTheDocument();
  });
});

// --- Integrity ------------------------------------------------------------------------------

describe("IntegrityPage", () => {
  function renderIntegrity() {
    return renderPage("/ops/integrity", <IntegrityPage />, "/ops/integrity");
  }

  it("runs a check, polls to done, and shows findings with severity", async () => {
    let status: "running" | "done" = "running";
    stubFetch({
      "GET /api/v1/integrity-reports": { body: { data: [] } },
      "POST /api/v1/integrity-checks": { body: { data: { report_id: "r1", status: "running" } } },
      "GET /api/v1/integrity-reports/r1": () => ({
        body: { data: integrityReport({ report_id: "r1", status, findings: status === "done" ? integrityReport().findings : [] }) },
      }),
    });
    const { client } = renderIntegrity();
    fireEvent.click(await screen.findByRole("button", { name: "Run check" }));
    expect(await screen.findByText("Check running…")).toBeInTheDocument();
    // Flip the server to done and force the poll (avoid waiting on the real 5s interval).
    status = "done";
    await client.invalidateQueries({ queryKey: ["c3", "integrity-report"] });
    await waitFor(() => expect(screen.getByText("Check complete")).toBeInTheDocument());
    expect(screen.getByText("Analyzed no detection")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
  });

  it("surfaces 409 check_running", async () => {
    stubFetch({
      "GET /api/v1/integrity-reports": { body: { data: [] } },
      "POST /api/v1/integrity-checks": { status: 409, body: { error: { code: "check_running", message: "running" } } },
    });
    renderIntegrity();
    fireEvent.click(await screen.findByRole("button", { name: "Run check" }));
    expect(await screen.findByText(/already running/)).toBeInTheDocument();
  });
});

// --- Activity -------------------------------------------------------------------------------

describe("ActivityPage", () => {
  function renderActivity() {
    return renderPage("/ops/activity", <ActivityPage />, "/ops/activity");
  }

  // Houses + rooms selects replace the old UUID text inputs.
  function houseList() {
    return {
      data: [{ house_id: HOUSE, tenant_id: TENANT, name: "Maple St", address: null, timezone: "America/Los_Angeles", owner_user_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }],
      meta: { page: 1, page_size: 100, total: 1 },
    };
  }

  async function pickHouse() {
    // Radix Select: open the trigger, then click the option.
    fireEvent.pointerDown(screen.getByRole("combobox", { name: "House" }), { button: 0 });
    fireEvent.click(screen.getByRole("combobox", { name: "House" }));
    const option = await screen.findByRole("option", { name: "Maple St" });
    fireEvent.click(option);
  }

  it("renders the 24-hour chart with a UTC axis after loading a house", async () => {
    stubFetch({
      "GET /api/v1/houses": { body: houseList() },
      "GET /api/v1/activity-patterns": { body: { data: [activity()] } },
    });
    renderActivity();
    await pickHouse();
    fireEvent.click(screen.getByRole("button", { name: "Load" }));
    expect(await screen.findByText("Detections per hour (UTC)")).toBeInTheDocument();
    expect(screen.getByText("00 UTC")).toBeInTheDocument();
    expect(screen.getByLabelText("14:00 UTC: 3 detections")).toBeInTheDocument();
    expect(screen.getByText("Normal")).toBeInTheDocument();
  });

  it("shows the collecting-data state when the baseline is not ready", async () => {
    stubFetch({
      "GET /api/v1/houses": { body: houseList() },
      "GET /api/v1/activity-patterns": {
        body: { data: [activity({ band: "insufficient_data", baseline_mean: null, baseline_std: null, anomaly_score: null })] },
      },
    });
    renderActivity();
    await pickHouse();
    fireEvent.click(screen.getByRole("button", { name: "Load" }));
    expect(await screen.findByText("Collecting data")).toBeInTheDocument();
    expect(screen.getByText(/needs at least 14 active days/)).toBeInTheDocument();
  });
});

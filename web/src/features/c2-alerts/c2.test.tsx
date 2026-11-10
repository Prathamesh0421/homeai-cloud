/** C2-13: api/c2.ts, display helpers, Alerts list and Alert Detail. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { alertAction, alertsQuery, getAlert, listAlerts } from "../../api/c2";
import AlertsPage from "./AlertsPage";
import AlertDetailPage from "./AlertDetailPage";
import {
  dayEndIso,
  dayStartIso,
  deliveryStatus,
  labelText,
  relativeTime,
  timelineLabel,
} from "./format";
import { HOUSE, detail, page, renderPage, signIn, stubFetch, summary } from "./testing";

const TYPES = page([{ code: "intrusion", name: "Possible intrusion" }, { code: "fall", name: "Possible fall" }]);

beforeEach(() => {
  sessionStorage.clear();
  signIn();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// --- display helpers -------------------------------------------------------------------------

describe("format", () => {
  const now = new Date("2026-11-05T12:00:00Z");

  it("says how long ago", () => {
    expect(relativeTime("2026-11-05T11:59:40Z", now)).toBe("just now");
    expect(relativeTime("2026-11-05T11:58:00Z", now)).toBe("2 m ago");
    expect(relativeTime("2026-11-05T09:00:00Z", now)).toBe("3 h ago");
    expect(relativeTime("2026-11-01T12:00:00Z", now)).toBe("4 d ago");
    expect(relativeTime("2026-11-05T12:05:00Z", now)).toBe("just now"); // clock skew
  });

  it("turns labels into words", () => {
    expect(labelText("glass_break")).toBe("Glass break");
    expect(labelText("dog")).toBe("Dog");
  });

  it("describes each delivery state", () => {
    const base = detail().notifications[1];
    expect(deliveryStatus(detail().notifications[0]).text).toBe("Shown in app");
    expect(deliveryStatus({ ...base, status: "sent" }).text).toBe("Sent");
    expect(deliveryStatus({ ...base, status: "queued" }).text).toBe("Sending…");
    expect(deliveryStatus(base)).toEqual({ text: "Pending confirmation (try 1/3)", tone: "pending" });
    expect(deliveryStatus({ ...base, attempt_count: 3 }).tone).toBe("failed");
    expect(deliveryStatus({ ...base, last_error: "sns publish failed", attempt_count: 2 }).text).toBe("Retry 2/3");
    expect(deliveryStatus({ ...base, last_error: "sns publish failed", attempt_count: 3 }).text).toBe(
      "Failed after 3 tries",
    );
    expect(deliveryStatus({ ...base, last_error: "alert_closed" }).text).toBe("Stopped: alert closed");
    expect(deliveryStatus({ ...base, last_error: "contact_removed" }).text).toBe("Stopped: contact removed");
  });

  it("writes timeline entries", () => {
    const raised = detail().timeline[0];
    expect(timelineLabel(raised)).toBe("Raised");
    expect(
      timelineLabel({ ...raised, from_status: "open", to_status: "acknowledged", actor_role: "house_owner", note: "on it" }),
    ).toBe("Acknowledged by house owner — “on it”");
  });

  it("makes the day range end exclusive", () => {
    const start = new Date(dayStartIso("2026-11-05"));
    const end = new Date(dayEndIso("2026-11-05"));
    expect(end.getTime() - start.getTime()).toBe(24 * 3600 * 1000);
  });
});

// --- api/c2.ts -------------------------------------------------------------------------------

describe("api/c2", () => {
  it("builds the list query", () => {
    expect(alertsQuery({ status: ["open", "acknowledged"], severity: "critical", houseId: HOUSE, page: 2 })).toBe(
      `status=open%2Cacknowledged&severity=critical&house_id=${HOUSE}&page=2&page_size=25`,
    );
    expect(alertsQuery({})).toBe("page=1&page_size=25");
  });

  it("keeps the page meta of a list", async () => {
    stubFetch({ "GET /api/v1/alerts": { body: page([summary()], 40) } });
    const result = await listAlerts({});
    expect(result.meta.total).toBe(40);
    expect(result.data[0].alert_type_name).toBe("Possible intrusion");
  });

  it("unwraps a detail and posts actions with the right bodies", async () => {
    const { calls } = stubFetch({
      "GET /api/v1/alerts/a1": { body: { data: detail() } },
      "POST /api/v1/alerts/a1/acknowledge": { body: { data: detail({ status: "acknowledged" }) } },
      "POST /api/v1/alerts/a1/resolve": { body: { data: detail({ status: "resolved" }) } },
      "POST /api/v1/alerts/a1/false-positive": { body: { data: detail({ status: "false_positive" }) } },
    });
    expect((await getAlert("a1")).allowed_actions).toEqual(["acknowledge", "false_positive"]);
    await alertAction("a1", "acknowledge", "  on my way ");
    await alertAction("a1", "resolve", "   ");
    await alertAction("a1", "false_positive", "dropped a glass");
    expect(calls.slice(1).map((c) => [c.url, c.body])).toEqual([
      ["/api/v1/alerts/a1/acknowledge", { note: "on my way" }],
      ["/api/v1/alerts/a1/resolve", undefined], // blank note -> no body
      ["/api/v1/alerts/a1/false-positive", { reason: "dropped a glass" }],
    ]);
  });
});

// --- Alerts list -----------------------------------------------------------------------------

describe("AlertsPage", () => {
  function renderList(path = "/alerts") {
    return renderPage(path, <AlertsPage />, "/alerts");
  }

  it("lists alerts with severity, status and where", async () => {
    stubFetch({
      "GET /api/v1/alerts": { body: page([summary(), summary({ alert_id: "a2", severity: "critical", status: "acknowledged", room_name: null })]) },
      "GET /api/v1/alert-types": { body: TYPES },
    });
    renderList();
    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(3); // header + 2
    expect(within(rows[1]).getByLabelText("Severity High")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Open")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Maple St · Kitchen")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Glass break")).toBeInTheDocument();
    expect(within(rows[1]).getByText("78%")).toBeInTheDocument();
    expect(within(rows[1]).getByText("2 m ago")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Acknowledged")).toBeInTheDocument();
  });

  it("shows when house names are unavailable (C1 down)", async () => {
    stubFetch({
      "GET /api/v1/alerts": { body: page([summary({ house_name: null, room_name: null })]) },
      "GET /api/v1/alert-types": { body: TYPES },
    });
    renderList();
    expect(await screen.findByText("House unavailable")).toBeInTheDocument();
  });

  it("sends the filters to the API and resets to page 1", async () => {
    const { calls } = stubFetch({
      "GET /api/v1/alerts": { body: page([summary()]) },
      "GET /api/v1/alert-types": { body: TYPES },
    });
    renderList("/alerts?page=3");
    await screen.findByText("Possible intrusion", { selector: "a" });
    fireEvent.change(screen.getByRole("combobox", { name: /^Severity/ }), { target: { value: "critical" } });
    fireEvent.change(screen.getByRole("combobox", { name: /^Status/ }), { target: { value: "open,acknowledged" } });
    fireEvent.change(screen.getByRole("combobox", { name: /^Type/ }), { target: { value: "fall" } });
    await waitFor(() => {
      const lists = calls.filter((c) => c.url.startsWith("/api/v1/alerts?"));
      const last = lists[lists.length - 1].url;
      expect(last).toContain("severity=critical");
      expect(last).toContain("status=open%2Cacknowledged");
      expect(last).toContain("alert_type_code=fall");
      expect(last).toContain("page=1&");
    });
    expect(calls[0].url).toContain("page=3");
  });

  it("offers the owner's houses as a filter", async () => {
    stubFetch({
      "GET /api/v1/alerts": { body: page([summary()]) },
      "GET /api/v1/alert-types": { body: TYPES },
    });
    renderList();
    const house = await screen.findByRole("combobox", { name: /^House/ });
    await waitFor(() => expect(within(house).getByText("Maple St")).toBeInTheDocument());
  });

  it("has empty and error states", async () => {
    stubFetch({ "GET /api/v1/alerts": { body: page([]) }, "GET /api/v1/alert-types": { body: TYPES } });
    const { unmount } = renderList();
    expect(await screen.findByText(/No alerts/)).toBeInTheDocument();
    unmount();

    stubFetch({
      "GET /api/v1/alerts": { status: 503, body: { error: { code: "dependency_unavailable", message: "c1 is unavailable" } } },
      "GET /api/v1/alert-types": { body: TYPES },
    });
    renderList();
    expect(await screen.findByText("Could not load alerts: c1 is unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("opens an alert from its row or link", async () => {
    stubFetch({ "GET /api/v1/alerts": { body: page([summary()]) }, "GET /api/v1/alert-types": { body: TYPES } });
    renderList();
    // The alert type name is a deep link to the full detail page; the row itself opens a drawer.
    fireEvent.click(await screen.findByRole("link", { name: "Possible intrusion" }));
    expect(await screen.findByTestId("detail-route")).toBeInTheDocument();
  });

  it("announces a new critical alert that arrives with a later poll", async () => {
    let rows = [summary()];
    stubFetch({ "GET /api/v1/alerts": () => ({ body: page(rows) }), "GET /api/v1/alert-types": { body: TYPES } });
    const { client } = renderList();
    await screen.findByText("Maple St · Kitchen");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // what was there on load is not "new"

    rows = [summary({ alert_id: "a9", severity: "critical", alert_type_name: "Smoke alarm" }), ...rows];
    await client.invalidateQueries({ queryKey: ["c2", "alerts"] });
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("1 new critical alert: Smoke alarm at Maple St");
    fireEvent.click(within(banner).getByText("Dismiss"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not call older criticals new when a filter or the page changes", async () => {
    const old = summary({ alert_id: "a8", severity: "critical", alert_type_name: "Smoke alarm" });
    // First load shows only the high alert (severity filter), then the filter is cleared.
    let rows = [summary()];
    stubFetch({
      "GET /api/v1/alerts": () => ({ body: page(rows, 30) }),
      "GET /api/v1/alert-types": { body: TYPES },
    });
    renderList("/alerts?severity=high");
    await screen.findByText("Maple St · Kitchen");
    rows = [old, summary()];
    fireEvent.change(screen.getByRole("combobox", { name: /^Severity/ }), { target: { value: "" } });
    await screen.findByText("Smoke alarm");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    rows = [summary({ alert_id: "a7", severity: "critical", alert_type_name: "Scream" })];
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Scream");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("labels the owner's houses apart before they appear in results", async () => {
    stubFetch({
      "GET /api/v1/alerts": { body: page([summary({ house_id: "22222222-0000-0000-0000-0000000000a2", house_name: "Oak Ave" })]) },
      "GET /api/v1/alert-types": { body: TYPES },
    });
    renderList();
    const house = await screen.findByRole("combobox", { name: /^House/ });
    await waitFor(() => expect(within(house).getByText("Oak Ave")).toBeInTheDocument());
    expect(within(house).getByText("House …00a1")).toBeInTheDocument();
  });

  it("polls every 15 seconds", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"], shouldAdvanceTime: true });
    try {
      const { calls } = stubFetch({
        "GET /api/v1/alerts": { body: page([summary()]) },
        "GET /api/v1/alert-types": { body: TYPES },
      });
      renderList();
      await screen.findByText("Maple St · Kitchen");
      const lists = () => calls.filter((c) => c.url.startsWith("/api/v1/alerts?")).length;
      expect(lists()).toBe(1);
      await vi.advanceTimersByTimeAsync(15_000);
      await waitFor(() => expect(lists()).toBe(2));
    } finally {
      vi.useRealTimers();
    }
  });
});

// --- Alert Detail ----------------------------------------------------------------------------

describe("AlertDetailPage", () => {
  function renderDetail() {
    return renderPage("/alerts/a1", <AlertDetailPage />, "/alerts/:alertId");
  }

  it("shows evidence, timeline and contacts", async () => {
    stubFetch({ "GET /api/v1/alerts/a1": { body: { data: detail() } } });
    renderDetail();
    expect(await screen.findByRole("heading", { name: "Possible intrusion" })).toBeInTheDocument();
    expect(screen.getByText(/alert threshold 55%/)).toBeInTheDocument();
    expect(screen.getByText("Model yamnet 1.0.0")).toBeInTheDocument();
    expect(screen.getByText("Speech")).toBeInTheDocument(); // second label bar
    expect(screen.getByText("Raised")).toBeInTheDocument();
    expect(screen.getByText("alice.maple@example.test")).toBeInTheDocument();
    expect(screen.getByText("Pending confirmation (try 1/3)")).toBeInTheDocument();
    expect(screen.getByText("Clip playback is not available yet.")).toBeInTheDocument();
  });

  it("enables only the allowed actions (resolve needs acknowledge first)", async () => {
    stubFetch({ "GET /api/v1/alerts/a1": { body: { data: detail() } } });
    renderDetail();
    expect(await screen.findByRole("button", { name: "Acknowledge" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Resolve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Mark false positive" })).toBeEnabled();
    expect(screen.getByText("Acknowledge the alert before resolving it.")).toBeInTheDocument();
  });

  it("acknowledges with the note and shows the new state", async () => {
    const { calls } = stubFetch({
      "GET /api/v1/alerts/a1": { body: { data: detail() } },
      "POST /api/v1/alerts/a1/acknowledge": {
        body: { data: detail({ status: "acknowledged", allowed_actions: ["resolve", "false_positive"] }) },
      },
    });
    renderDetail();
    fireEvent.change(await screen.findByLabelText(/Note/), { target: { value: "Checking the kitchen" } });
    fireEvent.click(screen.getByRole("button", { name: "Acknowledge" }));
    expect(await screen.findByText("Alert acknowledged")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolve" })).toBeEnabled();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ note: "Checking the kitchen" });
  });

  it("asks for a reason before marking a false positive", async () => {
    const { calls } = stubFetch({
      "GET /api/v1/alerts/a1": { body: { data: detail() } },
      "POST /api/v1/alerts/a1/false-positive": {
        body: { data: detail({ status: "false_positive", allowed_actions: [] }) },
      },
    });
    renderDetail();
    fireEvent.click(await screen.findByRole("button", { name: "Mark false positive" }));
    const dialog = screen.getByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Mark false positive" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Reason (required)"), { target: { value: "   " } });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Reason (required)"), { target: { value: "Dropped a glass" } });
    fireEvent.click(confirm);
    expect(await screen.findByText("This alert is closed; no further actions.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ reason: "Dropped a glass" });
  });

  it("keeps the typed reason when the page re-renders (e.g. a toast goes away)", async () => {
    const { FalsePositiveDialog } = await import("./FalsePositiveDialog");
    const { render } = await import("@testing-library/react");
    const view = render(<FalsePositiveDialog open onConfirm={() => {}} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Reason (required)"), { target: { value: "Dropped a glass" } });
    view.rerender(<FalsePositiveDialog open onConfirm={() => {}} onCancel={() => {}} />); // new inline handler
    expect(screen.getByLabelText("Reason (required)")).toHaveValue("Dropped a glass");
    view.rerender(<FalsePositiveDialog open={false} onConfirm={() => {}} onCancel={() => {}} />);
    view.rerender(<FalsePositiveDialog open onConfirm={() => {}} onCancel={() => {}} />);
    expect(screen.getByLabelText("Reason (required)")).toHaveValue(""); // reopened: empty
  });

  it("cancels the dialog with Escape", async () => {
    stubFetch({ "GET /api/v1/alerts/a1": { body: { data: detail() } } });
    renderDetail();
    fireEvent.click(await screen.findByRole("button", { name: "Mark false positive" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("on 409 shows the server's message and reloads the alert", async () => {
    let current = detail();
    const { calls } = stubFetch({
      "GET /api/v1/alerts/a1": () => ({ body: { data: current } }),
      "POST /api/v1/alerts/a1/acknowledge": () => {
        current = detail({ status: "acknowledged", allowed_actions: ["resolve", "false_positive"] });
        return {
          status: 409,
          body: { error: { code: "invalid_state", message: "cannot acknowledge an acknowledged alert" } },
        };
      },
    });
    renderDetail();
    fireEvent.click(await screen.findByRole("button", { name: "Acknowledge" }));
    expect(await screen.findByText("cannot acknowledge an acknowledged alert")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Resolve" })).toBeEnabled());
    expect(calls.filter((c) => c.method === "GET")).toHaveLength(2);
  });

  it("explains missing detection details (C3 down) and non-emailed severities", async () => {
    stubFetch({
      "GET /api/v1/alerts/a1": {
        body: {
          data: detail({
            severity: "medium",
            evidence: { ...detail().evidence, detection_available: false, model: null, threshold: null },
          }),
        },
      },
    });
    renderDetail();
    expect(await screen.findByText(/Detection details are unavailable/)).toBeInTheDocument();
    expect(screen.getByText("Emails go out for critical and high alerts only.")).toBeInTheDocument();
    expect(screen.queryByText(/alert threshold/)).not.toBeInTheDocument();
  });

  it("shows the demo link only when the API sends one", async () => {
    const withLink = detail();
    withLink.notifications[1] = { ...withLink.notifications[1], view_link: "http://localhost:8080/alert-view/tok" };
    stubFetch({ "GET /api/v1/alerts/a1": { body: { data: withLink } } });
    renderDetail();
    expect(await screen.findByRole("link", { name: "demo link" })).toHaveAttribute(
      "href",
      "http://localhost:8080/alert-view/tok",
    );
  });

  it.each([
    [404, "This alert does not exist (or was removed)."],
    [403, "You don't have access to this alert."],
  ])("handles %s", async (status, text) => {
    stubFetch({ "GET /api/v1/alerts/a1": { status, body: { error: { code: "x", message: "x" } } } });
    renderDetail();
    expect(await screen.findByText(text)).toBeInTheDocument();
  });
});

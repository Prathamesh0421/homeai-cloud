/** C2-14: Alert Rules page, rule form, and the rule calls in api/c2.ts. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { rulesQuery, syncSubscriptions, updateRule } from "../../api/c2";
import { fieldErrors } from "../../shared";
import RulesPage, { syncSummary } from "./RulesPage";
import { validate } from "./RuleForm";
import { ALERT_TYPES, TENANTS, page, renderPage, rule, signIn, stubFetch } from "./testing";

const HOUSE = "22222222-0000-0000-0000-0000000000a1";
const BATH = "33333333-0000-0000-0000-00000000a104";

beforeEach(() => {
  sessionStorage.clear();
  signIn("cloud_staff");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function routes(extra: Record<string, Parameters<typeof stubFetch>[0][string]> = {}, rules = [rule()]) {
  return stubFetch({
    "GET /api/v1/alert-rules": { body: page(rules) },
    "GET /api/v1/alert-types": { body: page(ALERT_TYPES) },
    "GET /api/v1/tenants": { body: { data: TENANTS } },
    ...extra,
  });
}

function renderRules(path = "/ops/alert-rules") {
  return renderPage(path, <RulesPage />, "/ops/alert-rules");
}

/** The open rule form (the filter bar has fields with the same labels). */
function form() {
  const title = screen.getByText(/^(New alert rule|Edit rule: )/);
  return within(title.closest("form")!);
}

async function tenantsLoaded() {
  await waitFor(() => expect(screen.getAllByRole("option", { name: "Acme Care" }).length).toBeGreaterThan(0));
}

// --- pure helpers ----------------------------------------------------------------------------

describe("rule helpers", () => {
  it("builds the rules query", () => {
    expect(rulesQuery({ tenantId: "t1", isEnabled: false, alertTypeCode: "fall" })).toBe(
      "tenant_id=t1&alert_type_code=fall&is_enabled=false&page=1&page_size=50",
    );
  });

  it("maps the contract's 422 details to fields", () => {
    expect(
      fieldErrors([
        { field: "trigger_labels.0", issue: "Input should be 'smoke_alarm', ..." },
        { field: "room_id", issue: "room does not belong to the house" },
        { field: "", issue: "ignored" },
      ]),
    ).toEqual({
      trigger_labels: ["Input should be 'smoke_alarm', ..."],
      room_id: ["room does not belong to the house"],
    });
  });

  it("validates before sending", () => {
    const base = {
      scope: "house" as const,
      tenantId: "",
      houseId: HOUSE,
      roomId: "",
      alertTypeCode: "fall",
      labels: ["fall_indicator"],
      minConfidence: "0.7",
      severity: "" as const,
      isEnabled: true,
    };
    expect(validate(base, false)).toEqual({});
    expect(validate({ ...base, houseId: "maple" }, false)).toHaveProperty("house_id");
    expect(validate({ ...base, minConfidence: "0.705" }, false)).toHaveProperty("min_confidence");
    expect(validate({ ...base, minConfidence: "1.5" }, false)).toHaveProperty("min_confidence");
    expect(validate({ ...base, labels: [] }, false)).toHaveProperty("trigger_labels");
    expect(validate({ ...base, scope: "tenant_default" }, false)).toHaveProperty("tenant_id");
    expect(validate({ ...base, scope: "tenant_default", tenantId: "t", roomId: BATH }, false)).toHaveProperty(
      "room_id",
    );
    expect(validate({ ...base, houseId: "", alertTypeCode: "" }, true)).toEqual({}); // fixed when editing
  });

  it("summarises a sync", () => {
    expect(syncSummary({ topics: 2, subscribed: 3, pending: 1, removed: 0, failed: 0 })).toBe(
      "2 house topic(s): 3 subscribed, 1 waiting for email confirmation",
    );
    expect(syncSummary({ topics: 1, subscribed: 0, pending: 0, removed: 2, failed: 1 })).toContain(
      "2 removed, 1 house(s) failed",
    );
  });

  it("sends If-Match with the rule version and the sync body", async () => {
    const { calls } = stubFetch({
      "PUT /api/v1/alert-rules/r1": { body: { data: rule({ version: 4 }) } },
      "POST /api/v1/alert-rules/subscriptions/sync": { body: { data: { topics: 0, subscribed: 0, pending: 0, removed: 0, failed: 0 } } },
    });
    await updateRule("r1", 3, { is_enabled: false });
    await syncSubscriptions();
    await syncSubscriptions(HOUSE);
    expect(calls[0].headers["If-Match"]).toBe('"3"');
    expect(calls[0].body).toEqual({ is_enabled: false });
    expect(calls[1].body).toEqual({});
    expect(calls[2].body).toEqual({ house_id: HOUSE });
  });
});

// --- page ------------------------------------------------------------------------------------

describe("RulesPage", () => {
  it("lists rules with scope, labels, threshold, severity and state", async () => {
    routes({}, [
      rule(),
      rule({
        rule_id: "r2",
        scope: "house",
        house_id: HOUSE,
        room_id: BATH,
        alert_type_code: "fall",
        alert_type_name: "Possible fall",
        trigger_labels: ["fall_indicator"],
        min_confidence: 0.7,
        severity: "critical",
        effective_severity: "critical",
        is_enabled: false,
        false_positive_count_30d: 2,
      }),
    ]);
    renderRules();
    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Possible intrusion")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Tenant default")).toBeInTheDocument();
    expect(within(rows[0]).getByText("default")).toBeInTheDocument(); // severity from the type
    expect(within(rows[0]).getByText("55%")).toBeInTheDocument();
    expect(within(rows[0]).getByRole("switch", { name: "Disable rule" })).toBeChecked();
    expect(within(rows[1]).getByText("House …00a1 · room …a104")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Fall indicator")).toBeInTheDocument();
    expect(within(rows[1]).getByRole("switch", { name: "Enable rule" })).not.toBeChecked();
    expect(within(rows[1]).getByText("2")).toBeInTheDocument();
  });

  it("filters by tenant, type and state", async () => {
    const { calls } = routes();
    renderRules();
    await screen.findAllByRole("listitem");
    fireEvent.change(screen.getByRole("combobox", { name: /^Tenant/ }), { target: { value: TENANTS[1].tenant_id } });
    fireEvent.change(screen.getByRole("combobox", { name: /^Enabled/ }), { target: { value: "false" } });
    await waitFor(() => {
      const lists = calls.filter((c) => c.url.startsWith("/api/v1/alert-rules?"));
      const last = lists[lists.length - 1].url;
      expect(last).toContain(`tenant_id=${TENANTS[1].tenant_id}`);
      expect(last).toContain("is_enabled=false");
    });
  });

  it("applies the house filter only for a whole id", async () => {
    const { calls } = routes();
    renderRules();
    await screen.findAllByRole("listitem");
    const input = screen.getByRole("textbox", { name: /^House id/ });
    fireEvent.change(input, { target: { value: "2222" } });
    expect(input).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(input, { target: { value: HOUSE } });
    await waitFor(() => {
      const lists = calls.filter((c) => c.url.startsWith("/api/v1/alert-rules?"));
      expect(lists.map((c) => c.url.includes("house_id="))).toEqual([false, true]); // no partial ids
    });
    expect(screen.getAllByText("Possible intrusion").length).toBeGreaterThan(0);
  });

  it("creates tenant defaults once a tenant is chosen", async () => {
    const { calls } = routes({ "POST /api/v1/alert-rules/defaults": { body: { data: { created: 7 } } } });
    renderRules();
    const button = await screen.findByRole("button", { name: "Create tenant defaults" });
    expect(button).toBeDisabled();
    await tenantsLoaded();
    fireEvent.change(screen.getByRole("combobox", { name: /^Tenant/ }), { target: { value: TENANTS[0].tenant_id } });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    expect(await screen.findByText("Created 7 default rule(s)")).toBeInTheDocument();
    expect(calls.find((c) => c.url === "/api/v1/alert-rules/defaults")!.body).toEqual({
      tenant_id: TENANTS[0].tenant_id,
    });
  });

  it("syncs email subscriptions and shows who still has to confirm", async () => {
    routes({
      "POST /api/v1/alert-rules/subscriptions/sync": {
        body: { data: { topics: 1, subscribed: 2, pending: 1, removed: 0, failed: 0 } },
      },
    });
    renderRules();
    fireEvent.click(await screen.findByRole("button", { name: "Sync email subscriptions" }));
    expect(await screen.findByText(/1 waiting for email confirmation/)).toBeInTheDocument();
    expect(screen.getByText(/must click the confirmation link/)).toBeInTheDocument();
  });

  it("says when a sync is already running (409)", async () => {
    routes({
      "POST /api/v1/alert-rules/subscriptions/sync": {
        status: 409,
        body: { error: { code: "sync_in_progress", message: "a subscription sync is already running" } },
      },
    });
    renderRules();
    fireEvent.click(await screen.findByRole("button", { name: "Sync email subscriptions" }));
    expect(await screen.findByText("A sync is already running; try again in a few seconds.")).toBeInTheDocument();
  });

  it("asks before disabling, then sends the version", async () => {
    const { calls } = routes({
      "PUT /api/v1/alert-rules/r0000000-0000-4000-8000-000000000001": {
        body: { data: rule({ is_enabled: false, version: 2 }) },
      },
    });
    renderRules();
    // Turning the enabled switch off asks for confirmation first.
    fireEvent.click(await screen.findByRole("switch", { name: "Disable rule" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Disable this rule?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Disable" }));
    expect(await screen.findByText("Rule disabled")).toBeInTheDocument();
    const put = calls.find((c) => c.method === "PUT")!;
    expect([put.body, put.headers["If-Match"]]).toEqual([{ is_enabled: false }, '"1"']);
  });

  it("reloads when someone else changed the rule first (412)", async () => {
    const { calls } = routes({
      "PUT /api/v1/alert-rules/r0000000-0000-4000-8000-000000000001": {
        status: 412,
        body: { error: { code: "version_mismatch", message: "rule changed" } },
      },
    });
    renderRules();
    fireEvent.click(await screen.findByRole("switch", { name: "Disable rule" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Disable" }));
    expect(await screen.findByText("This rule was changed by someone else; reloaded the list.")).toBeInTheDocument();
    await waitFor(() => expect(calls.filter((c) => c.url.startsWith("/api/v1/alert-rules?")).length).toBe(2));
  });

  it("has empty and error states", async () => {
    routes({}, []);
    const { unmount } = renderRules("/ops/alert-rules?tenant=" + TENANTS[0].tenant_id);
    expect(await screen.findByText(/This tenant has no matching rules/)).toBeInTheDocument();
    unmount();
    routes({ "GET /api/v1/alert-rules": { status: 500, body: { error: { code: "internal", message: "boom" } } } });
    renderRules();
    expect(await screen.findByText("Could not load rules: boom")).toBeInTheDocument();
  });
});

// --- form ------------------------------------------------------------------------------------

describe("RuleForm", () => {
  async function openNew() {
    const fetches = routes({
      "POST /api/v1/alert-rules": {
        status: 201,
        body: { data: rule({ rule_id: "r9", scope: "house", house_id: HOUSE, room_id: BATH }) },
      },
    });
    renderRules();
    fireEvent.click(await screen.findByRole("button", { name: "New rule" }));
    return fetches;
  }

  it("creates a room rule for a house (the demo's fall-in-Bathroom rule)", async () => {
    const { calls } = await openNew();
    fireEvent.change(form().getByLabelText("House id"), { target: { value: HOUSE } });
    fireEvent.change(form().getByLabelText("Alert type"), { target: { value: "fall" } });
    // Picking the type starts from its label and its default threshold.
    expect(form().getByRole("checkbox", { name: "Fall indicator" })).toBeChecked();
    expect(form().getByLabelText("Minimum confidence (0–1)")).toHaveAttribute("placeholder", "Type default 0.6");
    fireEvent.change(form().getByLabelText("Minimum confidence (0–1)"), { target: { value: "0.70" } });
    fireEvent.change(form().getByLabelText(/^Room id/), { target: { value: BATH } });
    fireEvent.click(screen.getByRole("button", { name: "Create rule" }));
    expect(await screen.findByText("Rule created")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({
      alert_type_code: "fall",
      trigger_labels: ["fall_indicator"],
      is_enabled: true,
      house_id: HOUSE,
      room_id: BATH,
      min_confidence: 0.7,
    });
    expect(screen.queryByText("New alert rule")).not.toBeInTheDocument(); // form closes
  });

  it("creates a tenant default without a house", async () => {
    const { calls } = await openNew();
    fireEvent.click(form().getByLabelText(/Tenant default/));
    await tenantsLoaded();
    fireEvent.change(form().getByLabelText("Tenant"), { target: { value: TENANTS[1].tenant_id } });
    fireEvent.change(form().getByLabelText("Alert type"), { target: { value: "intrusion" } });
    expect(form().queryByLabelText(/^Room id/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create rule" }));
    await screen.findByText("Rule created");
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({
      alert_type_code: "intrusion",
      trigger_labels: ["glass_break"],
      is_enabled: true,
      tenant_id: TENANTS[1].tenant_id,
    });
  });

  it("shows client checks without calling the API", async () => {
    const { calls } = await openNew();
    fireEvent.click(screen.getByRole("button", { name: "Create rule" }));
    expect(screen.getByText("Enter the house id (UUID)")).toBeInTheDocument();
    expect(screen.getByText("Choose an alert type")).toBeInTheDocument();
    expect(screen.getByText("Pick at least one label")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows the server's 422 next to the field", async () => {
    routes({
      "POST /api/v1/alert-rules": {
        status: 422,
        body: {
          error: {
            code: "validation_error",
            message: "request validation failed",
            details: [{ field: "room_id", issue: "room does not belong to the house" }],
          },
        },
      },
    });
    renderRules();
    fireEvent.click(await screen.findByRole("button", { name: "New rule" }));
    fireEvent.change(form().getByLabelText("House id"), { target: { value: HOUSE } });
    fireEvent.change(form().getByLabelText("Alert type"), { target: { value: "fall" } });
    fireEvent.change(form().getByLabelText(/^Room id/), { target: { value: BATH } });
    fireEvent.click(screen.getByRole("button", { name: "Create rule" }));
    expect(await screen.findByText("room does not belong to the house")).toBeInTheDocument();
    expect(screen.getByText("New alert rule")).toBeInTheDocument(); // stays open
  });

  it("toasts a duplicate (409) and reloads the list", async () => {
    const { calls } = routes({
      "POST /api/v1/alert-rules": {
        status: 409,
        body: { error: { code: "duplicate_rule", message: "an identical rule already exists" } },
      },
    });
    renderRules();
    fireEvent.click(await screen.findByRole("button", { name: "New rule" }));
    fireEvent.change(form().getByLabelText("House id"), { target: { value: HOUSE } });
    fireEvent.change(form().getByLabelText("Alert type"), { target: { value: "fall" } });
    fireEvent.click(screen.getByRole("button", { name: "Create rule" }));
    expect(await screen.findByText("an identical rule already exists")).toBeInTheDocument();
    await waitFor(() => expect(calls.filter((c) => c.url.startsWith("/api/v1/alert-rules?")).length).toBe(2));
  });

  it("edits with the version and can clear the severity override", async () => {
    const existing = rule({ severity: "critical", effective_severity: "critical", version: 5 });
    const { calls } = routes(
      { "PUT /api/v1/alert-rules/r0000000-0000-4000-8000-000000000001": { body: { data: rule({ version: 6 }) } } },
      [existing],
    );
    renderRules();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.getByText("Edit rule: Possible intrusion")).toBeInTheDocument();
    fireEvent.change(form().getByLabelText("Severity"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Rule saved")).toBeInTheDocument();
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.headers["If-Match"]).toBe('"5"');
    expect(put.body).toEqual({ severity: null }); // only what changed
  });

  it("sends only the changed field, so a room rule's edit does not depend on C1", async () => {
    const roomRule = rule({ scope: "house", house_id: HOUSE, room_id: BATH, min_confidence: 0.7, version: 2 });
    const { calls } = routes(
      { "PUT /api/v1/alert-rules/r0000000-0000-4000-8000-000000000001": { body: { data: rule({ version: 3 }) } } },
      [roomRule],
    );
    renderRules();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(form().getByLabelText("Minimum confidence (0–1)"), { target: { value: "0.75" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText("Rule saved");
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ min_confidence: 0.75 });
  });

  it("closes without a request when nothing changed", async () => {
    const { calls } = routes();
    renderRules();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByText(/^Edit rule:/)).not.toBeInTheDocument());
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("on 412 says so even if reloading the rule fails", async () => {
    routes({
      "PUT /api/v1/alert-rules/r0000000-0000-4000-8000-000000000001": {
        status: 412,
        body: { error: { code: "version_mismatch", message: "stale" } },
      },
      "GET /api/v1/alert-rules/r0000000-0000-4000-8000-000000000001": { status: 503, body: { error: { code: "x", message: "x" } } },
    });
    renderRules();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.click(form().getByRole("checkbox", { name: "Speech" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Close the form and open it again/)).toBeInTheDocument();
  });

  it("on 412 loads the latest version into the form", async () => {
    let version = 5;
    routes(
      {
        "PUT /api/v1/alert-rules/r0000000-0000-4000-8000-000000000001": () => {
          version = 6; // someone else saved first
          return { status: 412, body: { error: { code: "version_mismatch", message: "stale" } } };
        },
        "GET /api/v1/alert-rules/r0000000-0000-4000-8000-000000000001": () => ({
          body: { data: rule({ version, min_confidence: 0.8 }) },
        }),
      },
      [rule({ version: 5 })],
    );
    renderRules();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.click(form().getByRole("checkbox", { name: "Speech" })); // a change to save
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/changed by someone else. Reloaded the latest version/)).toBeInTheDocument();
    expect(form().getByLabelText("Minimum confidence (0–1)")).toHaveValue("0.8");
  });
});

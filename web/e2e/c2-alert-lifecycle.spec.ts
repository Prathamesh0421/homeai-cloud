/**
 * C2-17 (docs/05 §6): alert appears -> detail -> acknowledge -> resolve; rule create + duplicate
 * 409; public alert view, tampered and expired links. Runs against a full stack with C3 handing
 * off to C2 (EC2, or E2E_ALERT_ID with an open Maple alert). See playwright.config.ts.
 */
import { expect, test } from "@playwright/test";

import { ACME, MAPLE, MAPLE_BATHROOM, OPS, OWNER, call, closeAlert, raiseAlert, signIn, type AlertDetail } from "./stack";

test.describe.serial("C2 alert lifecycle", () => {
  let alertId = "";

  test.beforeAll(async ({ request }) => {
    alertId = await raiseAlert(request);
  });

  test.afterAll(async ({ request }) => {
    if (alertId) await closeAlert(request, alertId);
  });

  test("the public alert view opens from the email link, without signing in", async ({ browser, request }) => {
    const alert = await call<AlertDetail>(request, "GET", `/api/v1/alerts/${alertId}`, OWNER);
    const email = alert.notifications.find((n) => n.channel === "email" && n.view_link);
    test.skip(!email, "no email notification with a view link (DEMO_MODE off, or no contacts)");

    const visitor = await browser.newContext(); // a contact's phone: no session
    const page = await visitor.newPage();
    await page.goto(email!.view_link!);
    await expect(page.getByRole("heading", { name: alert.alert_type_name })).toBeVisible();
    await expect(page.getByRole("heading", { name: "What was heard" })).toBeVisible();
    if (email!.recipient) await expect(page.getByText(email!.recipient)).toHaveCount(0); // no PII

    // A changed signature is not a valid link.
    const url = new URL(email!.view_link!);
    const token = url.pathname.split("/").pop()!;
    const tampered = token.slice(0, -1) + (token.endsWith("A") ? "B" : "A");
    await page.goto(`/alert-view/${tampered}`);
    await expect(page.getByRole("heading", { name: "This link is not valid" })).toBeVisible();

    // An expired link (printed by `make demo-c2-expired-link`; signed with the real key).
    const expired = process.env.E2E_EXPIRED_LINK;
    if (expired) {
      await page.goto(expired);
      await expect(page.getByRole("heading", { name: "This link has expired" })).toBeVisible();
    } else {
      test.info().annotations.push({ type: "skipped part", description: "E2E_EXPIRED_LINK not set" });
    }
    await visitor.close();
  });

  test("the owner sees the alert, opens it, acknowledges and resolves it", async ({ page, request }) => {
    const alert = await call<AlertDetail>(request, "GET", `/api/v1/alerts/${alertId}`, OWNER);
    expect(alert.status, "the alert is still open").toBe("open");

    await signIn(page, OWNER);
    await page.goto("/alerts");
    const row = page.locator(`a[href="/alerts/${alertId}"]`).first();
    await expect(row).toBeVisible();
    await row.click();

    await expect(page).toHaveURL(new RegExp(`/alerts/${alertId}$`));
    await expect(page.getByRole("heading", { name: alert.alert_type_name, level: 1 })).toBeVisible();
    await expect(page.getByText("Contacts notified")).toBeVisible();

    const acknowledge = page.getByRole("button", { name: "Acknowledge" });
    const resolve = page.getByRole("button", { name: "Resolve", exact: true });
    await expect(resolve).toBeDisabled();
    await acknowledge.click();
    await expect(acknowledge).toBeDisabled();
    await expect(resolve).toBeEnabled();

    await page.getByLabel(/^Note/).fill("E2E: checked, all fine");
    await resolve.click();
    await expect(page.getByText("This alert is closed; no further actions.")).toBeVisible();
    expect((await call<AlertDetail>(request, "GET", `/api/v1/alerts/${alertId}`, OWNER)).status).toBe("resolved");
  });
});

test("ops creates a room rule; the same rule again is a duplicate (409)", async ({ page, request }) => {
  // An enabled Maple Bathroom rule for dog barking: only that room is affected, and it is deleted after.
  const find = () =>
    call<{ rule_id: string; room_id: string | null }[]>(
      request,
      "GET",
      `/api/v1/alert-rules?tenant_id=${ACME}&house_id=${MAPLE}&alert_type_code=pet`,
      OPS,
    ).then((rules) => rules.filter((r) => r.room_id === MAPLE_BATHROOM));
  expect(await find(), "no Maple Bathroom pet rule before the test").toEqual([]);

  try {
    await signIn(page, OPS);
    await page.goto("/ops/alert-rules");

    for (const expected of ["Rule created", "an enabled rule already exists for this tenant, house, alert type and room"]) {
      await page.getByRole("button", { name: "New rule" }).click();
      const form = page.locator("form").filter({ hasText: "New alert rule" });
      const house = form.getByLabel("House", { exact: true });
      await expect(house.locator(`option[value="${MAPLE}"]`)).toHaveCount(1);
      await house.selectOption(MAPLE);
      const room = form.getByLabel(/^Room/);
      await expect(room.locator(`option[value="${MAPLE_BATHROOM}"]`)).toHaveCount(1);
      await room.selectOption(MAPLE_BATHROOM);
      await form.getByLabel("Alert type").selectOption("pet");
      await form.getByRole("button", { name: "Create rule" }).click();
      await expect(page.getByText(expected)).toBeVisible();
      if (expected !== "Rule created") await form.getByRole("button", { name: "Cancel" }).click();
    }
    expect(await find()).toHaveLength(1);
  } finally {
    for (const r of await find()) await call(request, "DELETE", `/api/v1/alert-rules/${r.rule_id}`, OPS);
  }
});

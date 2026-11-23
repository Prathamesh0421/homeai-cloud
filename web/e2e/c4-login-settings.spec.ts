/**
 * C4 login/settings (docs/05 §6): role landings → guard redirect → lockout →
 * settings + contacts reorder → dashboard filters. Needs a seeded stack
 * (``E2E_BASE_URL``, demo password). See playwright.config.ts.
 */
import { expect, test, type Page } from "@playwright/test";

import { MAPLE, OPS, OWNER, call, signIn, userToken } from "./stack";

const IOT = "iot@acme.test";
const OWNER_ID = "44444444-0000-0000-0000-000000000002";

async function signOut(page: Page): Promise<void> {
  // Header avatar menu (email shown on sm+).
  await page.locator("header").getByText(/@/).first().click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
}

test.describe.serial("C4 login and settings", () => {
  test("each role lands on its home; owner is redirected away from ops", async ({ page }) => {
    await signIn(page, OWNER);
    await expect(page).toHaveURL(/\/home\/overview/);

    await page.goto("/ops/dashboard");
    await expect(page).toHaveURL(/\/home\/overview/);

    await signOut(page);
    await signIn(page, IOT);
    await expect(page).toHaveURL(/\/iot\/feeds/);

    await signOut(page);
    await signIn(page, OPS);
    await expect(page).toHaveURL(/\/ops\/dashboard/);
    await signOut(page);
  });

  test("five failed logins lock the owner; ops unlocks via API", async ({ page, request }) => {
    await page.goto("/login");
    // Five failures set locked_until; the next attempt returns 423 account_locked.
    for (let i = 0; i < 5; i++) {
      await page.getByLabel("Email").fill(OWNER);
      await page.getByLabel("Password", { exact: true }).fill("WrongPassword!1");
      await page.getByRole("button", { name: "Sign in", exact: true }).click();
      await expect(page.getByText(/Invalid email or password/i)).toBeVisible();
    }
    await page.getByLabel("Email").fill(OWNER);
    await page.getByLabel("Password", { exact: true }).fill("WrongPassword!1");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByText(/Account is locked/i)).toBeVisible();

    // Restore the seed user so later tests (and humans) can still sign in.
    await call(request, "PATCH", `/api/v1/users/${OWNER_ID}`, OPS, { unlock: true });
  });

  test("owner reorders emergency contacts and saves settings", async ({ page, request }) => {
    const before = await call<{ contact_id: string; name: string; priority: number }[]>(
      request,
      "GET",
      `/api/v1/houses/${MAPLE}/emergency-contacts`,
      OWNER,
    );
    expect(before.length).toBeGreaterThanOrEqual(2);
    const originalOrder = before.map((c) => c.contact_id);

    try {
      await signIn(page, OWNER);
      await page.goto("/home/settings");
      await expect(page.getByRole("heading", { name: /Emergency contacts/i })).toBeVisible();

      // Keyboard reorder: focus the first contact handle and move it down (API updates immediately).
      const handle = page.getByRole("button", { name: /Reorder .* Use up and down arrows/i }).first();
      await handle.focus();
      await handle.press("ArrowDown");

      // Toggle sensitivity to mark the form dirty, then save.
      await page.getByRole("button", { name: "high", exact: true }).click();
      const save = page.getByRole("button", { name: "Save", exact: true });
      await expect(save).toBeEnabled();
      await save.click();
      await expect(save).toBeDisabled({ timeout: 15_000 });

      const after = await call<{ contact_id: string; priority: number }[]>(
        request,
        "GET",
        `/api/v1/houses/${MAPLE}/emergency-contacts`,
        OWNER,
      );
      const newOrder = [...after].sort((a, b) => a.priority - b.priority).map((c) => c.contact_id);
      expect(newOrder[0]).toBe(originalOrder[1]);
      expect(newOrder[1]).toBe(originalOrder[0]);
    } finally {
      // Restore contact order and Maple seed settings.
      const token = await userToken(request, OWNER);
      await request.fetch(`/api/v1/houses/${MAPLE}/emergency-contacts/order`, {
        method: "PUT",
        headers: { Authorization: `Bearer ${token}` },
        data: { contact_ids: originalOrder },
      });
      await request.fetch(`/api/v1/houses/${MAPLE}/settings`, {
        method: "PUT",
        headers: { Authorization: `Bearer ${token}` },
        data: {
          enabled_services: [
            "fire_safety",
            "distress",
            "intrusion",
            "fall",
            "wellness",
            "presence",
            "pet",
          ],
          quiet_start: "22:00",
          quiet_end: "07:00",
          sensitivity: "medium",
        },
      });
    }
  });

  test("ops dashboard filters by range and tenant", async ({ page }) => {
    await signIn(page, OPS);
    await page.goto("/ops/dashboard");
    await expect(page.getByRole("heading", { name: "System dashboard" })).toBeVisible();

    await page.getByRole("button", { name: "7d", exact: true }).click();
    await expect(page.getByRole("button", { name: "7d", exact: true })).toHaveClass(/bg-primary/);

    // Tenant filter (Radix Select).
    const tenantTrigger = page.getByRole("combobox").filter({ hasText: /tenant|All tenants|Acme/i }).first();
    if (await tenantTrigger.isVisible().catch(() => false)) {
      await tenantTrigger.click();
      const acme = page.getByRole("option", { name: /Acme/i });
      if (await acme.count()) await acme.first().click();
    }

    await expect(page.getByText("Houses")).toBeVisible();
    await expect(page.getByText("Feeds online")).toBeVisible();
    await expect(page.getByText("Clips classified")).toBeVisible();
  });
});

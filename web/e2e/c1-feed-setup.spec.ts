/**
 * C1-14 (docs/05 §6): house/room → add feed → 409 room_required → enable → config v2 → upload →
 * clip listed. The C1 live demo (C1 plan §10.1 steps 1–5) as IoT staff, on a new house that is
 * removed afterwards, so the seeded houses are left as found. Needs a seeded stack
 * (E2E_BASE_URL) and demo_clips/ (scripts/fetch_demo_clips.sh). See playwright.config.ts.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type APIRequestContext } from "@playwright/test";

import { call, signIn, userToken } from "./stack";

const IOT = "iot@acme.test";
const run = Date.now().toString(36);
const HOUSE = `E2E Elm Ct ${run}`;
const FEED = "Hall Mic";
const CLIP = fileURLToPath(new URL("../../demo_clips/glass_break.wav", import.meta.url));

interface House {
  house_id: string;
  name: string;
}
interface Feed {
  feed_id: string;
  name: string;
  is_enabled: boolean;
  config_version: number;
  config: { capture_interval_s: number };
}

async function findHouse(api: APIRequestContext): Promise<House | undefined> {
  return (await call<House[]>(api, "GET", "/api/v1/houses?page_size=100", IOT)).find((h) => h.name === HOUSE);
}

async function feedsOf(api: APIRequestContext, houseId: string): Promise<Feed[]> {
  return call<Feed[]>(api, "GET", `/api/v1/feeds?house_id=${houseId}&page_size=100`, IOT);
}

test.describe.serial("C1 feed setup", () => {
  let houseId = "";
  let feedId = "";

  test.afterAll(async ({ request }) => {
    // Archive the test feeds, then the house can be deleted (house_not_empty otherwise).
    const house = await findHouse(request);
    if (!house) return;
    for (const f of await feedsOf(request, house.house_id)) {
      await call(request, "DELETE", `/api/v1/feeds/${f.feed_id}`, IOT);
    }
    await call(request, "DELETE", `/api/v1/houses/${house.house_id}`, IOT);
  });

  test("IoT staff add a house and two rooms", async ({ page, request }) => {
    await signIn(page, IOT);
    await expect(page).toHaveURL(/\/iot\/feeds/);
    await expect(page.getByRole("heading", { name: "Camera Feed Manager" })).toBeVisible();

    await page.goto("/iot/houses");
    await page.getByRole("button", { name: "+ Add house" }).first().click();
    const form = page.locator("form").filter({ hasText: "Add house" });
    await form.getByLabel("Name").fill(HOUSE);
    await form.getByLabel("Timezone (IANA)").fill("America/Los_Angeles");
    await form.getByRole("button", { name: "Add house" }).click();
    await expect(page.getByText(`House “${HOUSE}” added.`)).toBeVisible();

    // The new house opens its rooms panel (only one panel is open at a time).
    await expect(page.getByText(`Rooms in ${HOUSE}`)).toBeVisible();
    for (const [name, type] of [
      ["Hall", "living"],
      ["Kitchen", "kitchen"],
    ]) {
      await page.getByLabel("New room name").fill(name);
      await page.getByLabel("Type").selectOption(type);
      await page.getByRole("button", { name: "+ Add room" }).click();
      await expect(page.getByText(`Room “${name}” added.`)).toBeVisible();
    }

    const house = await findHouse(request);
    expect(house, "the house exists in C1").toBeTruthy();
    houseId = house!.house_id;
  });

  test("a feed added without a room is provisioned and cannot be enabled (409 room_required)", async ({
    page,
    request,
  }) => {
    await signIn(page, IOT);
    await page.goto("/iot/feeds");
    await page.getByRole("button", { name: "+ Add feed" }).first().click();
    const form = page.locator("form").filter({ hasText: "Add feed" });
    await form.getByLabel("Name").fill(FEED);
    await form.getByLabel("Kind").selectOption("audio");
    await form.getByLabel("House", { exact: true }).selectOption(houseId);
    await form.getByRole("button", { name: "Add feed" }).click();
    await expect(page.getByText(`Feed “${FEED}” added (provisioned, disabled).`)).toBeVisible();

    const [feed] = await feedsOf(request, houseId);
    expect(feed).toMatchObject({ name: FEED, is_enabled: false, config_version: 1 });
    feedId = feed.feed_id;

    await page.goto(`/iot/feeds/${feedId}`);
    await expect(page.getByRole("heading", { name: FEED, level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Enable" })).toBeDisabled();
    await expect(page.getByText("Assign a room before enabling this feed.")).toBeVisible();

    // The API refuses too (what the demo shows in Swagger).
    const res = await request.patch(`/api/v1/feeds/${feedId}/status`, {
      headers: { Authorization: `Bearer ${await userToken(request, IOT)}` },
      data: { is_enabled: true },
    });
    expect(res.status()).toBe(409);
    expect((await res.json()).error.code).toBe("room_required");
  });

  test("with a room the feed enables; a room in use cannot be deleted (409 room_in_use)", async ({
    page,
    request,
  }) => {
    await signIn(page, IOT);
    await page.goto(`/iot/feeds/${feedId}`);
    await page.locator("#feed-room-select").selectOption({ label: "Hall" });
    await page.getByRole("button", { name: "Save room" }).click();
    await expect(page.getByText("Room set to Hall.")).toBeVisible();

    const enable = page.getByRole("button", { name: "Enable" });
    await expect(enable).toBeEnabled();
    await enable.click();
    await expect(page.getByText("Feed enabled.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Disable" })).toBeVisible();
    expect((await call<Feed>(request, "GET", `/api/v1/feeds/${feedId}`, IOT)).is_enabled).toBe(true);

    await page.goto("/iot/houses");
    await page.getByRole("button", { name: HOUSE }).click();
    await page.locator("li").filter({ hasText: "Hall" }).getByRole("button", { name: "Delete" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "409 room_in_use" })).toBeVisible();
    await expect(page.locator("li").filter({ hasText: "Hall" })).toBeVisible();
  });

  test("config versioning: interval 30 → 10 is v2, restoring v1 is v3", async ({ page, request }) => {
    await signIn(page, IOT);
    await page.goto(`/iot/feeds/${feedId}`);
    await expect(page.getByText("Configuration · v1")).toBeVisible();

    await page.getByRole("button", { name: "Edit config" }).first().click();
    await page.locator("#cfg-interval").fill("10");
    await page.getByRole("button", { name: "Save as v2" }).click();
    await expect(page.getByText("Config saved as version 2.")).toBeVisible();
    await expect(page.getByText("Configuration · v2")).toBeVisible();

    await page.getByRole("row").filter({ has: page.getByText("v1", { exact: true }) }).getByRole("button", { name: "Restore" }).click();
    await expect(page.getByText("Restored v1 as version 3.")).toBeVisible();
    await expect(page.getByText("Configuration · v3")).toBeVisible();

    const feed = await call<Feed>(request, "GET", `/api/v1/feeds/${feedId}`, IOT);
    expect(feed).toMatchObject({ config_version: 3, config: { capture_interval_s: 30 } });
  });

  test("an uploaded clip is queued and listed in Recent clips and the Clip Library", async ({ page, request }) => {
    await signIn(page, IOT);
    await page.goto(`/iot/feeds/${feedId}`);
    await page.locator("#clip-file").setInputFiles({
      name: "glass_break.wav",
      mimeType: "audio/wav",
      buffer: readFileSync(CLIP),
    });
    await page.getByRole("button", { name: "Upload", exact: true }).click();
    const result = page.getByRole("status").filter({ hasText: "Uploaded." });
    await expect(result).toBeVisible();
    const mediaId = (await result.getByText(/^media_id /).textContent())!.replace("media_id ", "").trim();

    const clip = await call<{ feed_id: string; house_id: string; s3_key: string }>(
      request,
      "GET",
      `/api/v1/clips/${mediaId}`,
      IOT,
    );
    expect(clip).toMatchObject({ feed_id: feedId, house_id: houseId });
    expect(clip.s3_key).toContain(`/houses/${houseId}/`);

    // Recent clips: one row for the new clip (queued, or analyzed if C3 is running).
    await expect(page.getByRole("row").filter({ hasText: /Queued|Processing|Analyzed/ })).toHaveCount(1);

    await page.goto("/iot/clips");
    await expect(page.getByRole("heading", { name: "Clip Library" })).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: HOUSE }).filter({ hasText: FEED })).toHaveCount(1);
  });
});

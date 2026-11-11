/** C1-11..13: api/c1.ts, Feed Detail enable rules, Add feed 422 errors, Houses 409. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { ApiError } from "../../api/http";
import { feedsQuery, uploadClip } from "../../api/c1";
import ClipLibraryPage from "./clips/ClipLibraryPage";
import FeedDetailPage from "./feed-detail/FeedDetailPage";
import FeedManagerPage from "./feed-manager/FeedManagerPage";
import HousesPage from "./houses/HousesPage";
import { serverFieldErrors } from "./format";
import { FEED, HOUSE, ROOM, feed, house, page, renderPage, signIn, stubFetch } from "./testing";

beforeEach(() => {
  sessionStorage.clear();
  signIn();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const ROOMS = { data: [{ room_id: ROOM, house_id: HOUSE, name: "Hallway", room_type: "entry", created_at: "" }] };
const VERSIONS = {
  data: [
    {
      version: 1,
      capture_interval_s: 30,
      sensitivity: "medium",
      network_label: null,
      created_by: "u",
      created_at: "2026-11-10T00:00:00Z",
    },
  ],
};

function detailRoutes(f: ReturnType<typeof feed>) {
  return {
    [`GET /api/v1/feeds/${FEED}`]: { body: { data: f } },
    [`GET /api/v1/houses/${HOUSE}/rooms`]: { body: ROOMS },
    [`GET /api/v1/feeds/${FEED}/config-versions`]: { body: VERSIONS },
    "GET /api/v1/clips": { body: page([]) },
  };
}

describe("api/c1", () => {
  it("builds the feeds query", () => {
    expect(feedsQuery({ houseId: HOUSE, mediaKind: "audio", status: "active" })).toBe(
      `house_id=${HOUSE}&media_kind=audio&status=active&page=1&page_size=25`,
    );
  });

  it("uploads a clip as multipart with the bearer token", async () => {
    const { calls, fetchMock } = stubFetch({
      "POST /api/v1/ingest/clip": {
        status: 200,
        body: { data: { media_id: "m1", status: "queued", s3_key: "tenants/k.wav", duplicate: true } },
      },
    });
    const file = new File(["RIFF"], "glass_break.wav", { type: "audio/wav" });
    const res = await uploadClip({
      feedId: FEED,
      mediaKind: "audio",
      capturedAt: "2026-11-10T18:40:41Z",
      clientClipId: "hall-1",
      file,
    });
    expect(res.duplicate).toBe(true);
    const form = calls[0].body as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect(form.get("feed_id")).toBe(FEED);
    expect(form.get("media_kind")).toBe("audio");
    expect(form.get("captured_at")).toBe("2026-11-10T18:40:41Z");
    expect(form.get("client_clip_id")).toBe("hall-1");
    expect((form.get("file") as File).name).toBe("glass_break.wav");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toMatch(/^Bearer /);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("maps ingest errors to ApiError", async () => {
    stubFetch({
      "POST /api/v1/ingest/clip": {
        status: 422,
        body: { error: { code: "media_kind_mismatch", message: "feed is audio" } },
      },
    });
    const err = await uploadClip({
      feedId: FEED,
      mediaKind: "video",
      capturedAt: "2026-11-10T18:40:41Z",
      file: new Blob(["x"], { type: "video/mp4" }),
    }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(err.code).toBe("media_kind_mismatch");
  });

  it("keys nested 422 fields by their last part", () => {
    const err = new ApiError(422, "validation_error", "bad", [
      { field: "config.capture_interval_s", issue: "must be 5-3600" },
    ]);
    expect(serverFieldErrors(err)).toMatchObject({
      "config.capture_interval_s": "must be 5-3600",
      capture_interval_s: "must be 5-3600",
    });
  });
});

describe("Feed Detail", () => {
  it("disables Enable with a reason when the feed has no room", async () => {
    stubFetch(detailRoutes(feed()));
    renderPage(`/iot/feeds/${FEED}`, <FeedDetailPage />, "/iot/feeds/:feedId");

    const enable = await screen.findByRole("button", { name: "Enable" });
    expect(enable).toBeDisabled();
    expect(enable.parentElement).toHaveAttribute("title", "Assign a room before enabling this feed.");
    expect(screen.getByText("Assign a room before enabling this feed.")).toBeInTheDocument();
    const hint = screen.getByText(/The same client/).closest("span");
    expect(hint?.textContent).toMatch(/^Sent as an audio clip\./);
  });

  it("enables a feed that has a room and shows a 409 as a toast", async () => {
    const { calls } = stubFetch({
      ...detailRoutes(feed({ room_id: ROOM, room_name: "Hallway" })),
      [`PATCH /api/v1/feeds/${FEED}/status`]: {
        status: 409,
        body: { error: { code: "room_required", message: "feed needs a room" } },
      },
    });
    renderPage(`/iot/feeds/${FEED}`, <FeedDetailPage />, "/iot/feeds/:feedId");

    const enable = await screen.findByRole("button", { name: "Enable" });
    expect(enable).toBeEnabled();
    fireEvent.click(enable);

    await screen.findByText(/Assign a room to this feed before enabling it\. \(409 room_required\)/);
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toEqual({ is_enabled: true });
  });
});

describe("Clip Library", () => {
  it("tells same-named feeds of different houses apart", async () => {
    const OAK = "22222222-0000-0000-0000-0000000000a2";
    const OAK_FEED = "55555555-0000-4000-8000-000000000002";
    const clip = (media_id: string, house_name: string, feed_id: string) => ({
      media_id,
      house_name,
      feed_id,
      feed_name: "Kitchen Mic",
      room_name: "Kitchen",
      media_kind: "audio",
      captured_at: "2026-11-10T21:31:00Z",
      uploaded_at: "2026-11-10T21:31:02Z",
      size: 192_100,
      status: "analyzed",
      detection_id: null,
      top_label: "glass_break",
    });
    stubFetch({
      "GET /api/v1/houses": { body: page([house(), house({ house_id: OAK, name: "Oak Ave" })]) },
      "GET /api/v1/feeds": {
        body: page([
          feed({ name: "Kitchen Mic" }),
          feed({ feed_id: OAK_FEED, house_id: OAK, house_name: "Oak Ave", name: "Kitchen Mic" }),
        ]),
      },
      "GET /api/v1/clips": {
        body: page([
          clip("aaaaaaaa-0000-4000-8000-000000000001", "Maple St", FEED),
          clip("aaaaaaaa-0000-4000-8000-000000000002", "Oak Ave", OAK_FEED),
        ]),
      },
    });
    renderPage("/iot/clips", <ClipLibraryPage />, "/iot/clips");

    const table = await screen.findByRole("table");
    await within(table).findByText("Oak Ave");
    expect(within(table).getByRole("columnheader", { name: /House/ })).toBeInTheDocument();
    expect(within(table).getByText("Maple St")).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "Kitchen Mic · Oak Ave" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Kitchen Mic · Maple St" })).toBeInTheDocument();
  });
});

describe("Camera Feed Manager", () => {
  it("shows 422 field errors from the server next to the add-feed inputs", async () => {
    const { calls } = stubFetch({
      "GET /api/v1/houses": { body: page([house()]) },
      [`GET /api/v1/houses/${HOUSE}/rooms`]: { body: ROOMS },
      "GET /api/v1/feeds": { body: page([]) },
      "POST /api/v1/feeds": {
        status: 422,
        body: {
          error: {
            code: "validation_error",
            message: "invalid",
            details: [
              { field: "name", issue: "a feed with this name already exists in the house" },
              { field: "config.capture_interval_s", issue: "must be between 5 and 3600" },
            ],
          },
        },
      },
    });
    renderPage("/iot/feeds", <FeedManagerPage />, "/iot/feeds");

    await screen.findByText("No feeds yet");
    fireEvent.click(screen.getAllByRole("button", { name: "+ Add feed" })[0]);
    const form = screen.getByRole("heading", { name: "Add feed" }).closest("form")!;
    await waitFor(() => expect(within(form).getByLabelText("House")).toHaveValue(HOUSE));
    fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Hall Mic" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add feed" }));

    expect(await within(form).findByText("a feed with this name already exists in the house")).toBeInTheDocument();
    expect(within(form).getByText("must be between 5 and 3600")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toEqual({
      name: "Hall Mic",
      media_kind: "audio",
      house_id: HOUSE,
      config: { capture_interval_s: 30, sensitivity: "medium" },
    });
  });

  it("checks the capture interval before sending", async () => {
    const { calls } = stubFetch({
      "GET /api/v1/houses": { body: page([house()]) },
      [`GET /api/v1/houses/${HOUSE}/rooms`]: { body: ROOMS },
      "GET /api/v1/feeds": { body: page([]) },
    });
    renderPage("/iot/feeds", <FeedManagerPage />, "/iot/feeds");
    await screen.findByText("No feeds yet");
    fireEvent.click(screen.getAllByRole("button", { name: "+ Add feed" })[0]);
    const form = screen.getByRole("heading", { name: "Add feed" }).closest("form")!;
    fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Hall Mic" } });
    fireEvent.change(within(form).getByLabelText(/Capture interval/), { target: { value: "2" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add feed" }));

    expect(await within(form).findByText("Whole seconds between 5 and 3600.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
});

describe("Houses and Rooms", () => {
  it("shows house_not_empty when deleting a house with enabled feeds", async () => {
    stubFetch({
      "GET /api/v1/houses": { body: page([house()]) },
      [`DELETE /api/v1/houses/${HOUSE}`]: {
        status: 409,
        body: { error: { code: "house_not_empty", message: "house has enabled feeds" } },
      },
    });
    renderPage("/iot/houses", <HousesPage />, "/iot/houses");

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This house still has enabled feeds");
    expect(alert).toHaveTextContent("409 house_not_empty");
  });
});

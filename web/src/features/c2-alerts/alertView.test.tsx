/** C2-15: the public Alert View (no login) and its API call. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { getAlertView } from "../../api/c2";
import { getToken } from "../../api/http";
import AlertViewPage, { VIEW_REFRESH_MS } from "./AlertViewPage";
import { renderPage, signIn, stubFetch } from "./testing";

const URL_PATH = "/api/v1/alert-view/tok.sig";

function view(overrides = {}) {
  return {
    alert_type_name: "Possible intrusion",
    severity: "high",
    status: "open",
    house_name: "Maple St",
    room_name: "Kitchen",
    triggered_at: "2026-10-25T06:10:00Z",
    labels: [
      { label: "glass_break", confidence: 0.78 },
      { label: "speech", confidence: 0.1 },
    ],
    clip_url: null,
    expires_at: "2026-10-26T06:10:00Z",
    ...overrides,
  };
}

function renderView() {
  return renderPage("/alert-view/tok.sig", <AlertViewPage />, "/alert-view/:token");
}

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getAlertView", () => {
  it("sends no bearer token and does not log out a signed-in user on 401", async () => {
    signIn();
    const { calls } = stubFetch({
      [`GET ${URL_PATH}`]: { status: 401, body: { error: { code: "token_expired", message: "link expired" } } },
    });
    await expect(getAlertView("tok.sig")).rejects.toMatchObject({ status: 401, code: "token_expired" });
    expect(calls[0].headers).toEqual({}); // plain fetch, no Authorization
    expect(getToken()).not.toBeNull(); // still signed in
  });

  it("reads Retry-After on 429 and survives a non-JSON error page", async () => {
    stubFetch({
      [`GET ${URL_PATH}`]: {
        status: 429,
        headers: { "Retry-After": "12" },
        body: { error: { code: "rate_limited", message: "slow down" } },
      },
    });
    await expect(getAlertView("tok.sig")).rejects.toMatchObject({ status: 429, details: { retryAfter: 12 } });
    stubFetch({ [`GET ${URL_PATH}`]: { status: 502, raw: "<html>Bad Gateway</html>" } });
    await expect(getAlertView("tok.sig")).rejects.toMatchObject({ status: 502, code: "unknown" });
  });
});

describe("AlertViewPage", () => {
  it("shows the alert, what was heard, the 911 notice and the expiry", async () => {
    stubFetch({ [`GET ${URL_PATH}`]: { body: { data: view() } } });
    renderView();
    expect(await screen.findByRole("heading", { name: "Possible intrusion" })).toBeInTheDocument();
    expect(screen.getByLabelText("Severity High")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText(/Kitchen, Maple St/)).toBeInTheDocument();
    expect(screen.getByText("No one has responded yet.")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("If someone is in danger, call 911.");
    expect(screen.getByText("Glass break (78% confidence)")).toBeInTheDocument();
    expect(screen.getByText("The recording is not available.")).toBeInTheDocument();
    expect(screen.getByText(/This link is valid until/)).toBeInTheDocument();
  });

  it("plays the clip when there is one", async () => {
    stubFetch({ [`GET ${URL_PATH}`]: { body: { data: view({ clip_url: "https://s3.example/clip.wav?sig=1" }) } } });
    renderView();
    const player = await screen.findByLabelText("Alert recording");
    expect(player).toHaveAttribute("src", "https://s3.example/clip.wav?sig=1");
    expect(player.tagName).toBe("AUDIO"); // a .wav plays in <audio> (iPhone Safari)
  });

  it("plays a video clip in a video player", async () => {
    stubFetch({ [`GET ${URL_PATH}`]: { body: { data: view({ clip_url: "https://s3.example/clip.mp4?sig=1" }) } } });
    renderView();
    expect((await screen.findByLabelText("Alert recording")).tagName).toBe("VIDEO");
  });

  it("says when the status changed", async () => {
    stubFetch({ [`GET ${URL_PATH}`]: { body: { data: view({ status: "acknowledged", house_name: null, room_name: null }) } } });
    renderView();
    expect(await screen.findByText("The household or care team has seen this alert.")).toBeInTheDocument();
    expect(screen.getByText(/Location unavailable/)).toBeInTheDocument();
  });

  it.each([
    [401, {}, "This link has expired"],
    [404, {}, "This link is not valid"],
    [429, { "Retry-After": "30" }, "Too many requests"],
    [500, {}, "Could not load the alert"],
  ])("handles %s", async (status, headers, title) => {
    stubFetch({ [`GET ${URL_PATH}`]: { status, headers, body: { error: { code: "x", message: "x" } } } });
    renderView();
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.getByText("If someone is in danger, call 911.")).toBeInTheDocument();
    if (status === 429) expect(screen.getByText("Please try again in 30 seconds.")).toBeInTheDocument();
  });

  it("refreshes every 30 seconds while open", () => {
    expect(VIEW_REFRESH_MS).toBe(30_000);
  });
});

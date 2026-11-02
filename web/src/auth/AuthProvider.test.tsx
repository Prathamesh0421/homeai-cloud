/**
 * Tests for AuthProvider 401 handling: when http.ts clears the token via a 401,
 * the session is dropped.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, waitFor, act } from "@testing-library/react";
import { AuthProvider, useAuth } from "./AuthProvider";
import { clearToken, setToken } from "../api/http";

function Consumer() {
  const { session } = useAuth();
  return <div data-testid="state">{session ? "signed-in" : "signed-out"}</div>;
}

describe("AuthProvider 401 handling", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("drops the session when the token is cleared (simulating a 401)", async () => {
    // Seed a token directly so AuthProvider restores a session on mount.
    const fakeToken =
      "eyJhbGciOiJSUzI1NiJ9." +
      btoa(JSON.stringify({
        sub: "u1", role: "house_owner", tenant_id: "t1", house_ids: [], email: "o@acme.test", jti: "j1",
      })) +
      ".sig";
    setToken(fakeToken);

    const { getByTestId } = render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await waitFor(() => expect(getByTestId("state").textContent).toBe("signed-in"));

    // Simulate a 401 from http.ts, which calls clearToken().
    act(() => clearToken());

    await waitFor(() => expect(getByTestId("state").textContent).toBe("signed-out"));
  });
});

/**
 * Tests for RouteGuard redirects:
 * - No session → /login (preserving the intended destination).
 * - Wrong role → the user's own landing page.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AuthProvider, type Session } from "./AuthProvider";
import { RouteGuard } from "./RouteGuard";

// Helper: render with a pre-seeded session by stubbing sessionStorage + http.
function renderWithSession(session: Session | null, initialPath: string) {
  if (session) {
    const fakeToken =
      "eyJhbGciOiJSUzI1NiJ9." +
      btoa(JSON.stringify({
        sub: session.userId, role: session.role, tenant_id: session.tenantId,
        house_ids: session.houseIds, email: session.email, jti: "j1",
      })) +
      ".sig";
    sessionStorage.setItem("homeai.token", fakeToken);
  }
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<div data-testid="login">login</div>} />
          <Route path="/home/overview" element={<div data-testid="home">home</div>} />
          <Route path="/iot/feeds" element={<div data-testid="iot">iot</div>} />
          <Route path="/ops/dashboard" element={<div data-testid="ops">ops</div>} />
          <Route
            path="/ops/tenants"
            element={<RouteGuard allow={["cloud_staff"]}><div data-testid="tenants">tenants</div></RouteGuard>}
          />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

const ownerSession: Session = {
  token: "x", role: "house_owner", tenantId: "t1", houseIds: [], email: "o@acme.test", userId: "u1",
};

describe("RouteGuard redirects", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends an unauthenticated user to /login", () => {
    const { container } = renderWithSession(null, "/ops/tenants");
    expect(container.querySelector('[data-testid="login"]')).not.toBeNull();
  });

  it("redirects a house_owner opening a cloud_staff route to /home/overview", () => {
    const { container } = renderWithSession(ownerSession, "/ops/tenants");
    expect(container.querySelector('[data-testid="home"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="tenants"]')).toBeNull();
  });
});

/**
 * AppShell: sidebar by role, header with user menu (logout), and a content
 * outlet. Owners get a house picker in the header when they have more than one
 * house. This is the minimum shell for P0-8; the full kit (DataTable, etc.)
 * lands in C4-11.
 */

import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth, landingForRole, type Role } from "../auth/AuthProvider";

interface NavItem {
  to: string;
  label: string;
  roles: Role[];
}

const NAV: NavItem[] = [
  { to: "/home/overview", label: "Home Overview", roles: ["house_owner"] },
  { to: "/home/settings", label: "Services & Settings", roles: ["house_owner", "cloud_staff"] },
  { to: "/iot/feeds", label: "Camera Feeds", roles: ["iot_staff", "cloud_staff"] },
  { to: "/alerts", label: "Alerts", roles: ["house_owner", "cloud_staff"] },
  { to: "/ops/dashboard", label: "System Dashboard", roles: ["cloud_staff"] },
  { to: "/ops/tenants", label: "Tenants & Users", roles: ["cloud_staff"] },
  { to: "/ops/models", label: "Models", roles: ["cloud_staff"] },
  { to: "/ops/records", label: "Records", roles: ["cloud_staff"] },
];

const ROLE_LABEL: Record<Role, string> = {
  house_owner: "Home Owner",
  iot_staff: "IoT Staff",
  cloud_staff: "Cloud Staff",
};

export function AppShell() {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  if (!session) return null;
  const items = NAV.filter((n) => n.roles.includes(session.role));

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 border-r border-slate-200 bg-white">
        <div className="px-4 py-5 text-lg font-semibold text-slate-800">HomeAI Cloud</div>
        <nav className="px-2 space-y-1">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `block rounded px-3 py-2 text-sm ${
                  isActive ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
          <div className="text-sm text-slate-500">
            {ROLE_LABEL[session.role]} · {session.email}
          </div>
          <div className="relative">
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              className="rounded px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
            >
              Account
            </button>
            {menuOpen && (
              <div className="absolute right-0 mt-1 w-40 rounded border border-slate-200 bg-white py-1 shadow">
                <button
                  type="button"
                  onClick={handleLogout}
                  className="block w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-100"
                >
                  Sign out
                </button>
              </div>
            )}
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export { landingForRole };

/** AppShell: grouped sidebar (Monitor / Configure / Admin) with lucide icons,
 * an open-alert count badge on Alerts, and a header avatar menu. */

import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AudioLines,
  Bell,
  BookOpen,
  Building2,
  Cpu,
  Database,
  Film,
  LayoutDashboard,
  type LucideIcon,
  LogOut,
  Radio,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import { useAuth, landingForRole, type Role } from "../auth/AuthProvider";
import { listAlerts } from "../api/c2";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type NavGroup = "monitor" | "configure" | "admin";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  roles: Role[];
  group: NavGroup;
  badge?: "open-alerts";
}

const NAV: NavItem[] = [
  // Monitor
  { to: "/home/overview", label: "Home overview", icon: Activity, roles: ["house_owner"], group: "monitor" },
  { to: "/alerts", label: "Alerts", icon: Bell, roles: ["house_owner", "cloud_staff"], group: "monitor", badge: "open-alerts" },
  { to: "/home/feeds", label: "My feeds", icon: Radio, roles: ["house_owner"], group: "monitor" },
  { to: "/iot/feeds", label: "Camera feeds", icon: Radio, roles: ["iot_staff", "cloud_staff"], group: "monitor" },
  { to: "/home/clips", label: "Clip library", icon: Film, roles: ["house_owner"], group: "monitor" },
  { to: "/iot/clips", label: "Clip library", icon: Film, roles: ["iot_staff", "cloud_staff"], group: "monitor" },
  { to: "/ops/dashboard", label: "System dashboard", icon: LayoutDashboard, roles: ["cloud_staff"], group: "monitor" },
  { to: "/ops/activity", label: "Activity", icon: Activity, roles: ["cloud_staff"], group: "monitor" },
  // Configure
  { to: "/home/settings", label: "Services & settings", icon: Settings, roles: ["house_owner", "cloud_staff"], group: "configure" },
  { to: "/iot/houses", label: "Houses & rooms", icon: Building2, roles: ["iot_staff", "cloud_staff"], group: "configure" },
  { to: "/ops/alert-rules", label: "Alert rules", icon: SlidersHorizontal, roles: ["cloud_staff"], group: "configure" },
  { to: "/ops/models", label: "Models", icon: Cpu, roles: ["cloud_staff"], group: "configure" },
  { to: "/ops/classify", label: "Test classify", icon: AudioLines, roles: ["cloud_staff"], group: "configure" },
  // Admin
  { to: "/ops/tenants", label: "Tenants & users", icon: Users, roles: ["cloud_staff"], group: "admin" },
  { to: "/ops/records", label: "Records", icon: Database, roles: ["cloud_staff"], group: "admin" },
  { to: "/ops/integrity", label: "Integrity", icon: ShieldCheck, roles: ["cloud_staff"], group: "admin" },
  { to: "/ops/dictionary", label: "Data dictionary", icon: BookOpen, roles: ["cloud_staff"], group: "admin" },
];

const GROUP_LABEL: Record<NavGroup, string> = {
  monitor: "Monitor",
  configure: "Configure",
  admin: "Admin",
};

const ROLE_LABEL: Record<Role, string> = {
  house_owner: "Home owner",
  iot_staff: "IoT staff",
  cloud_staff: "Cloud staff",
};

function initials(email: string): string {
  const name = email.split("@")[0].split(/[._-]/);
  return ((name[0]?.[0] ?? "") + (name[1]?.[0] ?? name[0]?.[1] ?? "")).toUpperCase() || "?";
}

export function AppShell() {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  // Open-alert count for the Alerts badge. Only house_owner / cloud_staff can list
  // alerts; iot_staff would get 403 every 15 s.
  const canPollOpenAlerts =
    session?.role === "house_owner" || session?.role === "cloud_staff";
  const openAlerts = useQuery({
    queryKey: ["c2", "alerts", "open-count", "badge"],
    queryFn: () => listAlerts({ status: ["open", "acknowledged"], page: 1, pageSize: 1 }),
    refetchInterval: 15_000,
    enabled: Boolean(session) && canPollOpenAlerts,
  });

  if (!session) return null;

  const items = NAV.filter((n) => n.roles.includes(session.role));
  const groups: NavGroup[] = (["monitor", "configure", "admin"] as NavGroup[]).filter((g) =>
    items.some((i) => i.group === g),
  );
  const openCount = openAlerts.data?.meta.total ?? 0;

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="flex min-h-screen bg-canvas">
      <aside className="flex w-60 flex-col border-r border-border bg-surface">
        <div className="px-5 py-5">
          <div className="text-base font-semibold text-ink">HomeAI Cloud</div>
          <div className="mt-0.5 text-xs text-muted">Smart-home monitoring</div>
        </div>
        <nav className="flex-1 space-y-4 px-3 pb-4">
          {groups.map((group) => (
            <div key={group}>
              <div className="px-3 pb-1 text-[11px] font-medium uppercase tracking-wide text-muted/70">
                {GROUP_LABEL[group]}
              </div>
              <div className="space-y-0.5">
                {items
                  .filter((i) => i.group === group)
                  .map((item) => {
                    const Icon = item.icon;
                    return (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        className={({ isActive }) =>
                          `relative flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                            isActive
                              ? "bg-accent-soft font-medium text-accent"
                              : "text-muted hover:bg-surface-2 hover:text-ink"
                          }`
                        }
                      >
                        {({ isActive }) => (
                          <>
                            {isActive && (
                              <span
                                aria-hidden="true"
                                className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r bg-accent"
                              />
                            )}
                            <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                            <span className="flex-1">{item.label}</span>
                            {item.badge === "open-alerts" && openCount > 0 && (
                              <span className="tnum inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-sev-critical px-1.5 text-[11px] font-semibold text-white">
                                {openCount > 99 ? "99+" : openCount}
                              </span>
                            )}
                          </>
                        )}
                      </NavLink>
                    );
                  })}
              </div>
            </div>
          ))}
        </nav>
      </aside>
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border bg-surface/80 px-6 py-3 backdrop-blur">
          <div />
          <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex items-center gap-2 rounded-full py-1 pl-1 pr-2 text-sm text-muted hover:bg-surface-2 hover:text-ink focus-visible:outline-none"
              >
                <Avatar>
                  <AvatarFallback>{initials(session.email)}</AvatarFallback>
                </Avatar>
                <span className="hidden text-left sm:block">
                  <span className="block text-xs font-medium text-ink">{ROLE_LABEL[session.role]}</span>
                  <span className="block text-[11px] text-muted">{session.email}</span>
                </span>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>{session.email}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={handleLogout} className="text-danger gap-2">
                <LogOut className="h-4 w-4" aria-hidden="true" />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export { landingForRole };
// Re-export icon for Records nav reuse if needed elsewhere.
export { Database };

/**
 * App router. C4 owns the shell and the route guard; each owner fills their
 * own page components. Landings: house_owner → /home/overview, iot_staff →
 * /iot/feeds, cloud_staff → /ops/dashboard.
 */

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, landingForRole, useAuth } from "./auth/AuthProvider";
import { RouteGuard } from "./auth/RouteGuard";
import { AppShell } from "./shared/AppShell";
import Login from "./features/c4-dashboard/Login";
import HomeOverview from "./features/c4-dashboard/pages/HomeOverview";
import OpsDashboard from "./features/c4-dashboard/pages/OpsDashboard";
import IotFeeds from "./features/c4-dashboard/pages/IotFeeds";
import AlertsPage from "./features/c2-alerts/AlertsPage";
import AlertDetailPage from "./features/c2-alerts/AlertDetailPage";
import RulesPage from "./features/c2-alerts/RulesPage";
import AlertViewPage from "./features/c2-alerts/AlertViewPage";
import { ToastProvider, ToastViewport } from "./shared/Toasts";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

function RootRedirect() {
  const { session, loading } = useAuth();
  if (loading) return <div className="p-8 text-slate-500">Loading…</div>;
  if (!session) return <Navigate to="/login" replace />;
  return <Navigate to={landingForRole(session.role)} replace />;
}

function SettingsPlaceholder() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-slate-900">Services & Settings</h1>
      <div className="rounded border border-dashed border-slate-300 bg-white p-8 text-center text-slate-400">
        Service toggles, quiet hours, and emergency contacts land in C4-12.
      </div>
    </div>
  );
}

function TenantsPlaceholder() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-slate-900">Tenants & Users</h1>
      <div className="rounded border border-dashed border-slate-300 bg-white p-8 text-center text-slate-400">
        Tenant and user admin lands in C4-14.
      </div>
    </div>
  );
}

function ModelsPlaceholder() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-slate-900">Models</h1>
      <div className="rounded border border-dashed border-slate-300 bg-white p-8 text-center text-slate-400">
        Model registry and deployment UI is built by C3.
      </div>
    </div>
  );
}

function RecordsPlaceholder() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-slate-900">Records</h1>
      <div className="rounded border border-dashed border-slate-300 bg-white p-8 text-center text-slate-400">
        Classification records UI is built by C3.
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            {/* Public, no shell: emergency contacts open this from the alert email. */}
            <Route path="/alert-view/:token" element={<AlertViewPage />} />
            <Route
              element={
                <RouteGuard allow={["house_owner", "iot_staff", "cloud_staff"]}>
                  <AppShell />
                </RouteGuard>
              }
            >
              <Route path="/home/overview" element={<RouteGuard allow={["house_owner"]}><HomeOverview /></RouteGuard>} />
              <Route path="/home/settings" element={<RouteGuard allow={["house_owner", "cloud_staff"]}><SettingsPlaceholder /></RouteGuard>} />
              <Route path="/iot/feeds" element={<RouteGuard allow={["iot_staff", "cloud_staff"]}><IotFeeds /></RouteGuard>} />
              <Route path="/alerts" element={<RouteGuard allow={["house_owner", "cloud_staff"]}><AlertsPage /></RouteGuard>} />
              <Route path="/alerts/:alertId" element={<RouteGuard allow={["house_owner", "cloud_staff"]}><AlertDetailPage /></RouteGuard>} />
              <Route path="/ops/dashboard" element={<RouteGuard allow={["cloud_staff"]}><OpsDashboard /></RouteGuard>} />
              <Route path="/ops/alert-rules" element={<RouteGuard allow={["cloud_staff"]}><RulesPage /></RouteGuard>} />
              <Route path="/ops/tenants" element={<RouteGuard allow={["cloud_staff"]}><TenantsPlaceholder /></RouteGuard>} />
              <Route path="/ops/models" element={<RouteGuard allow={["cloud_staff"]}><ModelsPlaceholder /></RouteGuard>} />
              <Route path="/ops/records" element={<RouteGuard allow={["cloud_staff"]}><RecordsPlaceholder /></RouteGuard>} />
            </Route>
            <Route path="/" element={<RootRedirect />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
      <ToastViewport />
      </ToastProvider>
    </QueryClientProvider>
  );
}

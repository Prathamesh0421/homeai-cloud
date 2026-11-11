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
import SettingsPage from "./features/c4-dashboard/pages/SettingsPage";
import TenantsPage from "./features/c4-dashboard/pages/TenantsPage";
import TenantDetailPage from "./features/c4-dashboard/pages/TenantDetailPage";
import FeedManagerPage from "./features/c1-iot/feed-manager/FeedManagerPage";
import FeedDetailPage from "./features/c1-iot/feed-detail/FeedDetailPage";
import HousesPage from "./features/c1-iot/houses/HousesPage";
import ClipLibraryPage from "./features/c1-iot/clips/ClipLibraryPage";
import MyFeedsPage from "./features/c1-iot/my-feeds/MyFeedsPage";
import AlertsPage from "./features/c2-alerts/AlertsPage";
import AlertDetailPage from "./features/c2-alerts/AlertDetailPage";
import RulesPage from "./features/c2-alerts/RulesPage";
import AlertViewPage from "./features/c2-alerts/AlertViewPage";
import ModelsPage from "./features/c3-data/ModelsPage";
import ModelDetailPage from "./features/c3-data/ModelDetailPage";
import ClassifyPage from "./features/c3-data/ClassifyPage";
import RecordsPage from "./features/c3-data/RecordsPage";
import DictionaryPage from "./features/c3-data/DictionaryPage";
import IntegrityPage from "./features/c3-data/IntegrityPage";
import ActivityPage from "./features/c3-data/ActivityPage";
import { ToastProvider, ToastViewport } from "./shared/Toasts";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

function RootRedirect() {
  const { session, loading } = useAuth();
  if (loading) return <div className="p-8 text-muted">Loading…</div>;
  if (!session) return <Navigate to="/login" replace />;
  return <Navigate to={landingForRole(session.role)} replace />;
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
                <Route path="/home/settings" element={<RouteGuard allow={["house_owner", "cloud_staff"]}><SettingsPage /></RouteGuard>} />
                <Route path="/home/feeds" element={<RouteGuard allow={["house_owner"]}><MyFeedsPage /></RouteGuard>} />
                <Route path="/home/clips" element={<RouteGuard allow={["house_owner"]}><ClipLibraryPage /></RouteGuard>} />
                <Route path="/iot/feeds" element={<RouteGuard allow={["iot_staff", "cloud_staff"]}><FeedManagerPage /></RouteGuard>} />
                <Route path="/iot/feeds/:feedId" element={<RouteGuard allow={["iot_staff", "cloud_staff"]}><FeedDetailPage /></RouteGuard>} />
                <Route path="/iot/houses" element={<RouteGuard allow={["iot_staff", "cloud_staff"]}><HousesPage /></RouteGuard>} />
                <Route path="/iot/clips" element={<RouteGuard allow={["iot_staff", "cloud_staff"]}><ClipLibraryPage /></RouteGuard>} />
                <Route path="/alerts" element={<RouteGuard allow={["house_owner", "cloud_staff"]}><AlertsPage /></RouteGuard>} />
                <Route path="/alerts/:alertId" element={<RouteGuard allow={["house_owner", "cloud_staff"]}><AlertDetailPage /></RouteGuard>} />
                <Route path="/ops/dashboard" element={<RouteGuard allow={["cloud_staff"]}><OpsDashboard /></RouteGuard>} />
                <Route path="/ops/alert-rules" element={<RouteGuard allow={["cloud_staff"]}><RulesPage /></RouteGuard>} />
                <Route path="/ops/tenants" element={<RouteGuard allow={["cloud_staff"]}><TenantsPage /></RouteGuard>} />
                <Route path="/ops/tenants/:tenantId" element={<RouteGuard allow={["cloud_staff"]}><TenantDetailPage /></RouteGuard>} />
                <Route path="/ops/models" element={<RouteGuard allow={["cloud_staff"]}><ModelsPage /></RouteGuard>} />
                <Route path="/ops/models/:modelId" element={<RouteGuard allow={["cloud_staff"]}><ModelDetailPage /></RouteGuard>} />
                <Route path="/ops/classify" element={<RouteGuard allow={["cloud_staff"]}><ClassifyPage /></RouteGuard>} />
                <Route path="/ops/records" element={<RouteGuard allow={["cloud_staff"]}><RecordsPage /></RouteGuard>} />
                <Route path="/ops/dictionary" element={<RouteGuard allow={["cloud_staff"]}><DictionaryPage /></RouteGuard>} />
                <Route path="/ops/integrity" element={<RouteGuard allow={["cloud_staff"]}><IntegrityPage /></RouteGuard>} />
                <Route path="/ops/activity" element={<RouteGuard allow={["cloud_staff"]}><ActivityPage /></RouteGuard>} />
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

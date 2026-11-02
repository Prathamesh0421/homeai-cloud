/** Home Overview landing (house_owner). Shell for P0-8; full content in C4-13. */

import { useAuth } from "../../../auth/AuthProvider";

export default function HomeOverview() {
  const { session } = useAuth();
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-slate-900">Home Overview</h1>
      <p className="text-slate-600">
        Welcome, {session?.email}. KPI tiles, open alerts, and feed status will appear here.
      </p>
      <div className="rounded border border-dashed border-slate-300 bg-white p-8 text-center text-slate-400">
        Home Overview content is built in C4-13.
      </div>
    </div>
  );
}

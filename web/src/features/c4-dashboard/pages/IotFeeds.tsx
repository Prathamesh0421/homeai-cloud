/** Camera Feeds landing (iot_staff). Placeholder route so iot_staff has a
 * landing; C1 fills this page in C1-11. */

import { EmptyState } from "../../../shared/EmptyState";

export default function IotFeeds() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">Camera Feeds</h1>
      <EmptyState
        title="Feed management coming soon"
        description="Camera feed management is on the way."
      />
    </div>
  );
}

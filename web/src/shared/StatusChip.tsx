/** StatusChip: small label for alert/clip status. */

import { STATUS_CLASSES, STATUS_LABEL, type AlertStatus } from "./tokens";

export function StatusChip({ status }: { status: AlertStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_CLASSES[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

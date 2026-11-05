/** SeverityBadge: icon + word for alert severity. */

import { SEVERITY_CLASSES, SEVERITY_LABEL, type Severity } from "./tokens";

const SEVERITY_ICON: Record<Severity, string> = {
  critical: "▲",
  high: "◆",
  medium: "●",
  low: "◇",
  info: "ℹ",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold ${SEVERITY_CLASSES[severity]}`}
      aria-label={`Severity ${SEVERITY_LABEL[severity]}`}
    >
      <span aria-hidden="true">{SEVERITY_ICON[severity]}</span>
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

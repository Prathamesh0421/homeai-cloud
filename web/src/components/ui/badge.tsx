/** Badge — shadcn-style, restyled to safety-console tokens. */
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        neutral: "border-border bg-surface-2 text-muted",
        brand: "border-accent/30 bg-accent-soft text-accent",
        critical: "border-sev-critical/30 bg-sev-critical-soft text-sev-critical",
        high: "border-sev-high/30 bg-sev-high-soft text-sev-high",
        medium: "border-sev-medium/30 bg-sev-medium-soft text-sev-medium",
        low: "border-sev-low/30 bg-sev-low-soft text-sev-low",
        success: "border-success/30 bg-success-soft text-success",
        warning: "border-warning/30 bg-warning-soft text-warning",
        danger: "border-danger/30 bg-danger-soft text-danger",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { badgeVariants };

/** ActionBar: row of buttons (e.g. Create / Cancel). */

import type { ReactNode } from "react";

export function ActionBar({ children }: { children: ReactNode }) {
  return <div className="flex items-center gap-2">{children}</div>;
}

export interface ButtonProps {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit" | "reset";
  variant?: "primary" | "secondary" | "danger" | "ghost";
  disabled?: boolean;
  className?: string;
}

const VARIANTS: Record<NonNullable<ButtonProps["variant"]>, string> = {
  primary:
    "bg-primary text-white hover:bg-primary-hover shadow-card disabled:opacity-50",
  secondary:
    "border border-border-strong bg-surface text-ink hover:bg-surface-2 disabled:opacity-50",
  danger: "bg-danger text-white hover:bg-danger/90 disabled:opacity-50",
  ghost: "text-muted hover:bg-surface-2 disabled:opacity-50",
};

export function Button({
  children,
  onClick,
  type = "button",
  variant = "primary",
  disabled,
  className,
}: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md px-3.5 py-2 text-sm font-medium transition-colors ${VARIANTS[variant]} ${className ?? ""}`}
    >
      {children}
    </button>
  );
}

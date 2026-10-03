import type { ReactNode } from "react";
import type { Variant } from "@/lib/api";
import { VARIANT_COLOR, VARIANT_LABEL } from "@/lib/format";

export function Card({
  title,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-border bg-surface p-4 sm:p-5 ${className}`}>
      {(title || action) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          {title && <h2 className="text-sm font-semibold tracking-tight">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function MockBanner({ children }: { children?: ReactNode }) {
  return (
    <div
      role="status"
      className="rounded-lg border border-[var(--mock-border)] bg-[var(--mock-bg)] px-3 py-2 text-sm text-[var(--mock-fg)]"
    >
      <strong className="font-semibold">MOCK providers.</strong>{" "}
      {children ??
        "Results come from a rule-based mock stack, not a real model. They are not representative of production performance."}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
      {message}
    </div>
  );
}

export function VariantChip({ variant }: { variant: Variant }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs font-medium">
      <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: VARIANT_COLOR[variant] }} />
      {VARIANT_LABEL[variant]}
    </span>
  );
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "warn" | "danger" }) {
  const tones = {
    neutral: "border-border text-muted",
    ok: "border-ok/40 bg-ok/10 text-ok",
    warn: "border-warn/40 bg-warn/10 text-warn",
    danger: "border-danger/40 bg-danger/10 text-danger",
  };
  return <span className={`inline-block rounded-full border px-2 py-0.5 text-xs ${tones[tone]}`}>{children}</span>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-surface-2 ${className}`} />;
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="tabular mt-0.5 text-2xl font-semibold tracking-tight">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  );
}

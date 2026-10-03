"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Voice Agent" },
  { href: "/evaluation", label: "Evaluation" },
  { href: "/conversations", label: "Conversations" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-20 border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <span
            aria-hidden
            className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-sm text-accent-fg"
          >
            ◉
          </span>
          <span className="hidden sm:inline">Hinglish Sales Agent</span>
          <span className="sm:hidden">HSA</span>
        </Link>
        <nav className="flex gap-1" aria-label="Main">
          {LINKS.map((l) => {
            const active = l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={active ? "page" : undefined}
                className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
                  active
                    ? "bg-surface-2 font-medium text-foreground"
                    : "text-muted hover:bg-surface-2 hover:text-foreground"
                }`}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

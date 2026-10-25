import { cn } from "@/lib/utils"

/**
 * ax's mark: two strokes from opposite corners meeting in one place, as Claude's and
 * Codex's work meets in ax; the dot is what waits for you.
 */
export function AppIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-6", className)} aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="var(--primary)" />
      <path
        d="M9 9 L23 23 M23 9 L9 23"
        stroke="var(--primary-foreground)"
        strokeWidth="3.4"
        strokeLinecap="round"
      />
      <circle cx="23" cy="9" r="3.6" fill="var(--primary)" />
      <circle cx="23" cy="9" r="2.4" fill="var(--primary-foreground)" />
    </svg>
  )
}

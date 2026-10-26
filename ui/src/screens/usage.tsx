import { Eyebrow } from "@/blocks/primitives"
import { UsageDetails } from "@/blocks/usage-band"
import type { NowState } from "@/lib/ax"

/** Usage on a page of its own, for a phone, where nothing hovers. */
export function UsageScreen({ state }: { state: NowState }) {
  return (
    <main className="mx-auto max-w-[960px] space-y-4 p-4 md:p-6">
      <header className="space-y-1">
        <Eyebrow>Usage</Eyebrow>
        <h1 className="text-[22px] leading-tight">What's left of each tool</h1>
        <p className="text-sm text-muted-foreground">
          Every window of Claude and Codex, and what each weekly window leaves per day until it
          resets.
        </p>
      </header>
      <div className="panel p-4 md:p-5">
        <UsageDetails rows={state.usage} credits={state.credits ?? []} />
      </div>
    </main>
  )
}

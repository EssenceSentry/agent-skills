import { ArrowDown, ArrowRight } from "lucide-react"

import { Eyebrow } from "@/blocks/primitives"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { alone, areas, askFirst, commands, flow, intro } from "@/lib/help"
import { cn } from "@/lib/utils"

function Chips({ items }: { items: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((c) => (
        <code
          key={c}
          className="label-mono rounded-md bg-sunken px-1.5 py-0.5 text-[12px] text-ink-2 shadow-[inset_0_0_0_1px_var(--border)]"
        >
          {c}
        </code>
      ))}
    </div>
  )
}

/** Everything ax does, opened from the ? in the app bar. */
export function HelpScreen() {
  return (
    <main className="mx-auto max-w-[1080px] space-y-12 p-4 pb-20 md:p-6 md:pb-24">
      <header className="max-w-[760px] space-y-4 pt-4">
        <Eyebrow>Help</Eyebrow>
        <h1 className="text-[30px] leading-[1.1] text-balance md:text-[40px]">What ax does</h1>
        <p className="text-[17px] leading-relaxed text-pretty text-ink-2">{intro}</p>
      </header>

      <section className="space-y-4">
        <div className="space-y-1.5">
          <Eyebrow>How it fits together</Eyebrow>
          <h2 className="text-xl">Both tools in, one memory kept, help where you work</h2>
        </div>
        <div className="grid grid-cols-1 items-stretch gap-3 md:grid-cols-[1fr_auto_1fr_auto_1fr]">
          {flow.map((column, i) => (
            <div key={column.title} className="contents">
              {i > 0 && (
                <div className="flex items-center justify-center text-faint">
                  <ArrowRight className="hidden size-5 md:block" />
                  <ArrowDown className="size-5 md:hidden" />
                </div>
              )}
              <div className={cn("panel space-y-3 p-5", i === 1 && "bg-primary-soft/50")}>
                <div className="eyebrow">{column.title}</div>
                <ul className="space-y-2 text-[14px] leading-snug">
                  {column.items.map((item) => (
                    <li key={item} className="flex gap-2">
                      <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-primary/70" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <div className="space-y-1.5">
          <Eyebrow>What it does</Eyebrow>
          <h2 className="text-xl">Area by area, with what each has shown</h2>
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {areas.map((a) => (
            <section key={a.id} className="panel flex min-w-0 flex-col gap-3 p-5">
              <Eyebrow>{a.area}</Eyebrow>
              <h3 className="text-[16px] leading-snug">{a.title}</h3>
              <p className="text-[14px] leading-relaxed text-ink-2">{a.body}</p>
              <Chips items={a.commands} />
              {a.proof && (
                <p className="mt-auto border-t pt-3 text-[13px] leading-relaxed">
                  <span className="font-medium">Shown so far: </span>
                  <span className="text-ink-2">{a.proof}</span>
                </p>
              )}
            </section>
          ))}
        </div>
      </section>

      <section className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4">
          <div className="space-y-1.5">
            <Eyebrow>Every command</Eyebrow>
            <h2 className="text-xl">Each one has --help</h2>
          </div>
          <div className="panel overflow-x-auto p-2">
            <Table className="text-[13px]">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-[38%]">Command</TableHead>
                  <TableHead>What it does</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {commands.map(([name, what]) => (
                  <TableRow key={name}>
                    <TableCell className="label-mono align-top text-[12px] whitespace-normal">
                      {name}
                    </TableCell>
                    <TableCell className="whitespace-normal text-ink-2">{what}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
        <aside className="h-fit min-w-0 rounded-[var(--radius)] border-l-[3px] border-primary bg-primary-soft/60 p-6">
          <Eyebrow>What agents may do alone</Eyebrow>
          <ul className="mt-3 list-disc space-y-1.5 pl-5 text-[14px] leading-relaxed">
            {alone.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
          <div className="eyebrow mt-5">And what they ask you first</div>
          <ul className="mt-3 list-disc space-y-1.5 pl-5 text-[14px] leading-relaxed">
            {askFirst.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </aside>
      </section>
    </main>
  )
}

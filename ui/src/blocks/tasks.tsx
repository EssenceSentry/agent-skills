import { Check, Circle, CircleDashed, ListChecks } from "lucide-react"

import { taskCount } from "@/lib/activity"
import type { TaskStatus, Tasks } from "@/lib/sessions"
import { cn } from "@/lib/utils"

const MARK: Record<TaskStatus, typeof Check> = {
  completed: Check,
  in_progress: Circle,
  pending: CircleDashed,
}

/**
 * The turn's task list, as the desktop app shows it: each step with its state, the one in
 * progress marked; folded away once every step is done.
 */
export function TaskList({ tasks }: { tasks: Tasks }) {
  const count = taskCount(tasks)
  const finished = tasks.items.every((t) => t.status === "completed")
  return (
    <details
      open={!finished}
      className="chat-tasks rounded-xl border bg-card px-3.5 py-2.5 text-[13px]"
      aria-label={`Tasks: ${count}`}
    >
      <summary className="chat-tasks-head flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
        <ListChecks className="size-3.5" aria-hidden />
        Tasks · {count}
      </summary>
      {tasks.explanation && (
        <p className="mt-2 text-xs text-muted-foreground">{tasks.explanation}</p>
      )}
      <ol className="mt-2 space-y-1.5">
        {tasks.items.map((task, i) => {
          const Mark = MARK[task.status]
          return (
            <li
              // biome-ignore lint/suspicious/noArrayIndexKey: steps are kept in order
              key={i}
              data-status={task.status}
              aria-current={task.status === "in_progress" ? "step" : undefined}
              className={cn(
                "chat-task flex items-start gap-2",
                task.status === "completed" && "text-muted-foreground"
              )}
            >
              <Mark
                className={cn(
                  "mt-0.5 size-3.5 shrink-0",
                  task.status === "in_progress" && "animate-pulse text-primary"
                )}
                aria-hidden
              />
              <span>{task.text}</span>
            </li>
          )
        })}
      </ol>
    </details>
  )
}

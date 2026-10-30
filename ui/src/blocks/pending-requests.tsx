import { useState } from "react"
import type { PendingRequest, Session } from "@/lib/sessions"
import { QuestionPanel } from "./question"
import { ApprovalPanel, PlanPanel } from "./request"

type Answer = (payload: Record<string, unknown>) => void
type Schema = {
  type?: string
  title?: string
  enum?: string[]
  required?: string[]
  properties?: Record<string, Schema>
  minimum?: number
  maximum?: number
  minLength?: number
  maxLength?: number
  description?: string
  items?: Schema
}

function Elicitation({
  request,
  answer,
  busy,
}: {
  request: PendingRequest
  answer: Answer
  busy: boolean
}) {
  const [values, setValues] = useState<Record<string, unknown>>({})
  const params = request.elicitation ?? {}
  const data = (params.request ?? params) as {
    requestedSchema?: Schema
    url?: string
    message?: string
  }
  const schema = data.requestedSchema
  return (
    <form
      className="rounded-xl border bg-card p-4 text-sm"
      onSubmit={(e) => {
        e.preventDefault()
        answer({
          action: "answer",
          request: request.id,
          allow: true,
          response: {
            action: "accept",
            content: {
              ...Object.fromEntries(
                Object.entries(schema?.properties ?? {})
                  .filter(([, field]) => field.type === "boolean")
                  .map(([name]) => [name, false])
              ),
              ...values,
            },
          },
        })
      }}
    >
      <p>{data.message ?? request.summary}</p>
      {data.url && (
        <a href={data.url} target="_blank" rel="noreferrer" className="underline">
          Open requested authorization page
        </a>
      )}
      {Object.entries(schema?.properties ?? {}).map(([name, field]) => (
        <label key={name} htmlFor={`${request.id}:${name}`} className="my-2 block">
          {field.title ?? name}
          {field.description && (
            <small className="block text-muted-foreground">{field.description}</small>
          )}
          {field.enum ? (
            <select
              id={`${request.id}:${name}`}
              required={schema?.required?.includes(name)}
              value={String(values[name] ?? "")}
              onChange={(e) => setValues({ ...values, [name]: e.target.value })}
            >
              <option value="">Choose…</option>
              {field.enum.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          ) : field.type === "array" && field.items?.enum ? (
            <select
              id={`${request.id}:${name}`}
              multiple
              required={schema?.required?.includes(name)}
              value={(values[name] as string[]) ?? []}
              onChange={(e) =>
                setValues({
                  ...values,
                  [name]: Array.from(e.target.selectedOptions, (option) => option.value),
                })
              }
            >
              {field.items.enum.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          ) : field.type === "array" || field.type === "object" ? (
            <textarea
              id={`${request.id}:${name}`}
              className="block w-full rounded border bg-background p-1.5"
              required={schema?.required?.includes(name)}
              placeholder={
                field.type === "array" ? 'JSON array, for example ["one", "two"]' : "JSON object"
              }
              onChange={(e) => {
                try {
                  const value = e.target.value ? JSON.parse(e.target.value) : undefined
                  e.target.setCustomValidity("")
                  setValues({ ...values, [name]: value })
                } catch {
                  e.target.setCustomValidity("Enter valid JSON")
                }
              }}
            />
          ) : field.type === "boolean" ? (
            <input
              id={`${request.id}:${name}`}
              type="checkbox"
              checked={values[name] === true}
              onChange={(e) => setValues({ ...values, [name]: e.target.checked })}
            />
          ) : (
            <input
              id={`${request.id}:${name}`}
              className="block w-full rounded border bg-background p-1.5"
              type={field.type === "number" || field.type === "integer" ? "number" : "text"}
              required={schema?.required?.includes(name)}
              min={field.minimum}
              max={field.maximum}
              minLength={field.minLength}
              maxLength={field.maxLength}
              step={field.type === "integer" ? 1 : "any"}
              value={String(values[name] ?? "")}
              onChange={(e) =>
                setValues({
                  ...values,
                  [name]:
                    field.type === "number" || field.type === "integer"
                      ? Number(e.target.value)
                      : e.target.value,
                })
              }
            />
          )}
        </label>
      ))}
      <div className="mt-3 flex flex-wrap gap-4">
        <button type="submit" disabled={busy}>
          {data.url ? "I completed this flow" : "Submit"}
        </button>
        {["decline", "cancel"].map((action) => (
          <button
            key={action}
            type="button"
            disabled={busy}
            onClick={() =>
              answer({ action: "answer", request: request.id, allow: false, response: { action } })
            }
          >
            {action}
          </button>
        ))}
      </div>
    </form>
  )
}

function Permissions({
  request,
  answer,
  busy,
}: {
  request: PendingRequest
  answer: Answer
  busy: boolean
}) {
  const raw = JSON.parse(request.detail ?? "{}") as { permissions?: Record<string, unknown> }
  const permissions = raw.permissions ?? {}
  const [removed, setRemoved] = useState<Set<string>>(new Set())
  const [scope, setScope] = useState("turn")
  const choices: { id: string; label: string }[] = []
  const choose = (value: unknown, path = ""): unknown => {
    if (Array.isArray(value))
      return value.filter((item, n) => {
        const id = `${path}.${n}`
        const pretty = typeof item === "string" ? item : JSON.stringify(item)
        choices.push({ id, label: `${path.split(".").at(-1)}: ${pretty}` })
        return !removed.has(id)
      })
    if (value && typeof value === "object")
      return Object.fromEntries(
        Object.entries(value).map(([key, v]) => [key, choose(v, path ? `${path}.${key}` : key)])
      )
    choices.push({ id: path, label: `${path}: ${String(value)}` })
    return removed.has(path) ? null : value
  }
  const grant = choose(permissions)
  return (
    <section className="rounded-xl border bg-card p-4 text-sm" aria-label="Requested permissions">
      <h3>Additional permissions</h3>
      {request.reason && <p>{request.reason}</p>}
      {choices.map((choice) => (
        <label key={choice.id} className="my-2 flex items-start gap-2 break-all">
          <input
            type="checkbox"
            checked={!removed.has(choice.id)}
            onChange={(e) =>
              setRemoved((was) => {
                const next = new Set(was)
                if (e.target.checked) next.delete(choice.id)
                else next.add(choice.id)
                return next
              })
            }
          />
          {choice.label}
        </label>
      ))}
      <label>
        Duration{" "}
        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="turn">This turn</option>
          <option value="session">This session</option>
        </select>
      </label>
      <div className="mt-3 flex gap-4">
        <button
          type="button"
          disabled={busy}
          onClick={() => answer({ action: "answer", request: request.id, allow: false })}
        >
          Deny
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            answer({
              action: "answer",
              request: request.id,
              allow: true,
              response: { permissions: grant, scope },
            })
          }
        >
          Allow selected permissions
        </button>
      </div>
    </section>
  )
}

export function PendingRequests({
  requests,
  session,
  answer,
  busy,
}: {
  requests: PendingRequest[]
  session: Session
  answer: Answer
  busy: boolean
}) {
  return (
    <div className="space-y-3">
      {requests.map((request) =>
        request.kind === "question" ? (
          <QuestionPanel
            key={request.id}
            questions={request.questions ?? []}
            busy={busy}
            onAnswer={(answers) =>
              answer({ action: "answer-question", request: request.id, answers })
            }
            onSkipAll={
              request.via === "claude"
                ? () => answer({ action: "answer", request: request.id, allow: false })
                : undefined
            }
          />
        ) : request.kind === "elicitation" ? (
          <Elicitation key={request.id} request={request} answer={answer} busy={busy} />
        ) : request.tool === "permissions" ? (
          <Permissions key={request.id} request={request} answer={answer} busy={busy} />
        ) : request.plan != null ? (
          <PlanPanel
            key={request.id}
            plan={request.plan}
            provider={session.provider}
            cwd={session.cwd}
            busy={busy}
            onAnswer={(allow, message) =>
              answer({ action: "answer", request: request.id, allow, message })
            }
          />
        ) : (
          <ApprovalPanel
            key={request.id}
            approval={request}
            provider={session.provider}
            busy={busy}
            onAnswer={(allow, response) =>
              answer({ action: "answer", request: request.id, allow, response })
            }
          />
        )
      )}
    </div>
  )
}

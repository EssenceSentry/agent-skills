// The ax job dashboard: polls /api/job and fills the page with text only.
"use strict";

const $ = (id) => document.getElementById(id);
let job = null;

// The link carries the access token. Keep it for this tab and take it out of the
// address bar; every refresh sends it in a header, so no cookie is needed.
let token = new URLSearchParams(location.search).get("token");
try {
  if (token) sessionStorage.setItem("axJobToken", token);
  else token = sessionStorage.getItem("axJobToken");
} catch (error) {
  // Storage can be off (private browsing); the token stays in memory for this page.
}
if (location.search) history.replaceState(null, "", "/");

function duration(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h) return `${h} h ${m} min`;
  if (m) return `${m} min ${s} s`;
  return `${s} s`;
}

// An interval as you would say it: 45 s, 10 min, 90 min, 2 h, 1 d.
function every(seconds) {
  for (const [size, unit] of [[86400, "d"], [3600, "h"], [60, "min"]]) {
    if (seconds >= size && (seconds % size === 0 || seconds >= 10 * size)) {
      return `${Number((seconds / size).toFixed(1))} ${unit}`;
    }
  }
  return seconds >= 60 ? `${Number((seconds / 60).toFixed(1))} min` : `${seconds} s`;
}

function ago(iso) {
  if (!iso) return "-";
  return `${duration((Date.now() - Date.parse(iso)) / 1000)} ago`;
}

function clock(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function finishRange(finish) {
  // "7:24 PM (7:24 to 7:31 PM)"; dates appear only when the range leaves today.
  const days = [finish.p10, finish.p50, finish.p90].map((iso) => new Date(iso).toDateString());
  const today = days.every((day) => day === new Date().toDateString());
  const show = (iso) =>
    today
      ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : clock(iso);
  return `${show(finish.p50)} (${show(finish.p10)} to ${show(finish.p90)})`;
}

function stamp(iso) {
  // Events: the time with seconds today, the date as well on other days.
  const when = new Date(iso);
  const today = when.toDateString() === new Date().toDateString();
  const time = when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return today ? time : `${when.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
}

function counts(data) {
  if (data.done === null && data.total === null) return "";
  const n = (value) => (value === null ? "?" : String(Number(value)));
  const text = data.total ? `${n(data.done)}/${n(data.total)}` : n(data.done);
  return data.unit ? `${text} ${data.unit}` : text;
}

function describe(event) {
  const d = event.data || {};
  switch (event.type) {
    case "created": return "registered";
    case "status": return `status: ${d.status}${d.message ? ` (${d.message})` : ""}`;
    case "stage": return `stage: ${d.stage}`;
    case "message": return d.message;
    case "check_error": return `check failed: ${d.error}`;
    case "notified": return `sent: ${d.title}`;
    case "notify_failed": return `not sent: ${d.title}`;
    case "woke": return `woke the ${d.agent} session`;
    case "wake_failed": return `could not wake: ${d.error}`;
    default: return `${event.type} ${JSON.stringify(d)}`;
  }
}

function times() {
  if (!job) return;
  const end = job.finished ? Date.parse(job.finished) : Date.now();
  $("elapsed").textContent = duration((end - Date.parse(job.created)) / 1000);
  $("updated").textContent = ago(job.updated);
}

function render(data) {
  job = data;
  document.title = `${data.key} · ${data.status}`;
  $("key").textContent = data.key;
  $("label").textContent = data.label || [data.kind, data.ref].filter(Boolean).join(" · ");
  $("status").textContent = data.status;
  $("status").dataset.status = data.status;
  $("bar").dataset.status = data.status;

  const known = data.total && data.done !== null;
  const pct = known ? Math.min(100, (100 * data.done) / data.total) : null;
  // No bar when the job reports no total: an endless sliding bar says nothing.
  $("bar").hidden = !known && data.status !== "done";
  $("fill").style.width = known ? `${pct}%` : data.status === "done" ? "100%" : "";
  $("pct").textContent = known ? `${pct.toFixed(0)}%` : "";
  $("counts").textContent = counts(data);
  // The estimate's 80% interval; "basis" says whether it comes from this job's
  // progress or from how long similar jobs took.
  const eta = data.status === "running" ? data.eta : null;
  $("eta").textContent = eta ? `${eta.text}${eta.basis === "history" ? " (from past runs)" : ""}` : "";
  $("finish").textContent = eta ? finishRange(eta.finish) : data.finished ? clock(data.finished) : "-";
  $("stage").textContent = data.stage ? `Stage: ${data.stage}` : "";
  $("message").textContent = data.message || "";
  $("check").hidden = !data.check_error;
  $("check").textContent = data.check_error ? `Last check failed: ${data.check_error}` : "";

  $("started").textContent = clock(data.created);
  $("source").textContent = [data.kind, data.ref].filter(Boolean).join(" · ");
  $("console").hidden = !data.console_url;
  if (data.console_url) $("console").href = data.console_url;

  const list = $("events");
  list.replaceChildren(
    ...data.events.slice().reverse().map((event) => {
      const item = document.createElement("li");
      const when = document.createElement("time");
      when.textContent = stamp(event.ts);
      const what = document.createElement("span");
      what.textContent = describe(event);
      item.append(when, what);
      return item;
    }),
  );

  const looks = data.looks || [];
  $("looks-card").hidden = !looks.length && !data.check_every;
  $("looks-every").textContent = data.check_every ? `every ${every(data.check_every)}` : "";
  $("looks").replaceChildren(
    ...looks.map((look) => {
      const item = document.createElement("li");
      const when = document.createElement("time");
      when.textContent = stamp(look.at);
      const what = document.createElement("div");
      const summary = document.createElement("span");
      summary.textContent = look.summary || "(no summary)";
      what.append(summary);
      if (look.problem) {
        const problem = document.createElement("p");
        problem.className = "warning";
        problem.textContent = look.problem;
        what.append(problem);
      }
      item.append(when, what);
      return item;
    }),
  );

  $("log-card").hidden = data.log === undefined;
  if (data.log !== undefined) {
    const pre = $("log");
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
    pre.textContent = data.log || "(no output yet)";
    if (atBottom) pre.scrollTop = pre.scrollHeight;
  }
  times();
}

async function load() {
  try {
    const response = await fetch("/api/job", {
      cache: "no-store",
      credentials: "same-origin",
      headers: token ? { "X-Ax-Token": token } : {},
    });
    if (response.status === 401) {
      $("conn").textContent = "Open this dashboard with its full link; it carries an access token.";
      return;
    }
    if (!response.ok) throw new Error(String(response.status));
    render(await response.json());
    $("conn").textContent = "Refreshes every 5 s.";
  } catch (error) {
    $("conn").textContent = "The dashboard is offline; the follower has probably stopped.";
  }
}

load();
setInterval(load, 5000);
setInterval(times, 1000);

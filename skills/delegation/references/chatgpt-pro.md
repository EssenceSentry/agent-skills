# ChatGPT Pro consultation

Treat ChatGPT Pro as a professor, not a worker. Bring it a goal and a genuine
question with the evidence behind it; let it challenge premises, reframe the
problem, and choose its own method. Claude mechanics (runner, profiles, usage
helper) do not apply here.

## When Pro is the right target

For detailed infographic image generation, use [ChatGPT web with Extra High](chatgpt-infographics.md), **never Pro**, even when the subject is technically complex. This is the user's explicit routing preference.

Use Pro when the difficulty is the reasoning itself: exceptionally hard
mathematics or statistics, literature synthesis, adversarial analysis of a
design or argument, algorithms and optimization, or implementing a genuinely
difficult bounded module from scratch across many passes. Pro can run code in
its sandbox and return files, so ask for a working artifact when that is the
real goal; do not reduce it to advice. Route well-specified execution to Claude.

Consulting Pro conserves parent context: one rich submission can replace a long
parent investigation. A long turnaround is acceptable for substantial reasoning work.

## Quota and timing

Check the actual account's allowance and selected mode when this affects the
assignment. Entitlements and response times vary. This skill implements no Pro
usage reader. Inspect visible account information when relevant and available;
otherwise remaining usage and reset time are unknown. Claude and Codex quotas
cannot measure Pro usage.

Consolidate related questions: one well-prepared submission with
full context and related questions beats several thin ones. A follow-up is another
submission, but do not avoid a useful follow-up merely to save one. If the UI
reports a limit, tell the user; do not silently switch models or billing.

## Lifecycle

Pro submissions have their own gate. General delegation authorization does not
waive it. If the user later revises this protocol, follow the latest instruction.

1. **Prepare.** Write the exact question and collect artifact links (see below).
   Save it locally in the task's private run area, not in published source.
2. **Ask.** Tell the user you intend to consult Pro and show the concrete
   submission: the full question text (or a clickable link to the saved question), each
   artifact link with its visibility, new or existing conversation, and why Pro.
   Wait for explicit approval. If the user's approval already names this exact
   question and these artifacts, do not ask again. A material change after
   approval needs fresh approval.
3. **Send once.** Prefer native app messaging into the approved ChatGPT
   conversation with Pro already selected (mechanics below). Browser submission
   is a fallback. Confirm acceptance and record the conversation ID and URL;
   acceptance does not establish response completion.
4. **Return control.** Tell the user it was sent, give the URL, and state that
   retrieval resumes when they say the response is ready. Continue independent work or end the
   turn. Never wait, poll, monitor, schedule a check, set a heartbeat, or ask
   the user for completion updates. Do not infer failure from elapsed time.
5. **Retrieve on the user's signal.** When the user says the answer is ready,
   read the exact conversation through the native reader first. Check freshness,
   pagination, and truncation. Use the recorded URL if the native result is stale
   or incomplete, or to retrieve files through supported tools. If Pro is still
   running, report that observation and return control without polling.
   Reconnecting and reading the reported result need no new submission approval.
6. **Review.** Pro's answer is strong evidence, not sign-off. Check its key
   claims at the real failure surface: rerun its computation, test returned
   code against real interfaces, verify cited sources. Integrate only reviewed
   work and report what you verified.

Every subsequent message to Pro, including a clarification or follow-up,
is a new submission: prepare, ask, send once, return control.

### Local record

Keep a small record next to the saved question: conversation ID and URL,
submission route, submission time with timezone, evidence for the selected model,
the exact text sent, artifact links with commit SHAs or Drive file IDs, and status
(`sent`, `retrieved`, `reviewed`). Keep a separate entry for each approved submission,
including follow-ups. This record preserves continuity for later retrieval; it is not a monitor.

For an older completed consultation, use its saved conversation ID/URL to read
the original messages natively, without sending another Pro question. When the
record is missing, use the active/archived lookup workflow in
[older and archived conversations](chatgpt-app-tools.md#older-and-archived-conversations).
The user's request for that historical retrieval authorizes the read; the
readiness-signal rule still applies to unfinished consultations.

## Writing the question

Start from a consequential unanswered question, not a preferred artifact type.
A report, notebook, proof, module, or visualization may help answer it, but its
format is secondary. Let Pro choose the form of reasoning and evidence unless
the user has a genuine output constraint.

Treat the quality of the question as work for which the parent is accountable.
Reserve Pro for genuinely difficult reasoning: identify the precise uncertainty,
why ordinary advice or the parent's own analysis cannot settle it, and which
choice would change with the answer. Supply enough evidence and tentative
reasoning to reach that frontier; do not ask Pro to repeat resolved groundwork.

Ask incisive, particular questions about the actual difficulty. For example,
which assumption distinguishes two plausible mechanisms, whether an estimator
still targets the deployed object after a specific refit, or what evidence could
discriminate competing explanations. Where useful, ask for the decisive
counterexample, derivation, bound, or experiment. Choose these for their ability
to resolve the question, not as a mandatory deliverable checklist.

Include the relevant known facts, competing approaches and their tradeoffs,
unknowns, and firm constraints. Distinguish assumptions from requirements and
invite Pro to challenge the framing. Favor a coherent research question over a
generic request for best practices or a long collection of loosely related tasks. Do not predetermine the answer.

For open research questions, consult Pro as a professor who can guide the
investigation. Explicitly requesting a critical literature review is useful:
ask which bodies of work apply, what their evidence and assumptions establish,
where results disagree or fail to transfer, and which research avenues are worth
pursuing. Offer a few promising directions as starting points, not an exhaustive
taxonomy or prescribed route. Incisive questions should deepen the inquiry while
leaving room to discover a better framing; do not prematurely narrow a broad
learning question to one favored technical mechanism.

A short, open research brief can pose a genuinely difficult question. Let the
problem and the required research judgment supply the depth. Give the minimum
context needed, using established conversation or repository context when
available. Detailed background, formal notation, fixed comparison axes and many
subquestions are optional; do not turn an exploratory request into a long
technical rubric. An avenue such as data augmentation can be suggested without
limiting the investigation to it. Invite synthetic or downloaded-data experiments
when useful, leaving Pro to decide whether they would resolve uncertainty.

For a coherent research problem, aim to assign the complete investigation in one
initial prompt. Supply the relevant context and authorized data at the outset,
and make Pro responsible for identifying and resolving consequential gaps as it
works. Literature review, mathematical analysis, experiments, stronger controls,
and revisions to conclusions can all belong to that assignment; let Pro choose
which are useful rather than waiting for separate prompts to deepen each stage.

Define completion through the decision the evidence must support and the
uncertainty that matters. Encourage Pro to pursue promising findings and failures
while useful, feasible work remains. Subsequent interaction should mainly supply
unavailable information or decisions requiring the user's judgment. A useful
follow-up remains appropriate when new evidence changes the question; each new
submission still follows the approval protocol above.

### Worked example: a complete limited-data investigation

This user-approved revision preserves the original professor-style question and
gives Pro responsibility for the research through its recommendation. Adapt the
repository context and dataset link to the current task; the methods mentioned
are possible avenues, not a required sequence.

> I need a literature review and your recommendation on how best to use our
> limited labeled data across training, calibration, testing, and sometimes the
> feature-projection stage. Use the project context and the
> [development dataset](https://example.org/project/development-dataset),
> reading its README for provenance and limitations.
>
> What does the literature suggest, and which approaches actually make sense for
> our pipeline? Consider data augmentation and other promising avenues you
> identify. In particular, under what conditions can labels be reused across
> stages, and how should our choices change with the amount and structure of
> available data? Account for the total labels needed, including method selection
> and evaluation.
>
> Take responsibility for the full investigation. Read relevant literature, work
> through the mathematical conditions behind consequential claims, and perform
> experiments that help resolve uncertainty. Use our data, synthetic data, or
> suitable public datasets as appropriate.
>
> Choose the research direction yourself. Follow promising results and failures
> into further investigation, compare against credible simpler alternatives, and
> challenge your own explanations. When an important question can be investigated
> with the resources available, carry out that work before concluding.
>
> I want to understand what we should do, why, and under which conditions that
> recommendation would change. Distinguish established results, your experimental
> evidence, and remaining hypotheses; explain any consequential uncertainty you
> could not resolve.

### Check the question before submission

Before submission, judge whether a competent routine answer could satisfy the
prompt without resolving the hard uncertainty. If so, sharpen the question or
handle it locally. Do not manufacture complexity, demand a long response, or
request prolonged thinking to make the consultation seem difficult. Assess the
answer by what it establishes and changes, not by elapsed thinking time.

For independent review, use a fresh conversation with neutral evidence and no
expected verdict. In collaborative consultation, sharing our tentative
reasoning and uncertainty is useful; distinguish those two purposes.

## Sharing material

The user has GitHub and Google Drive available to Pro and the parent. Verify
that the linked material is accessible in the actual conversation; connector
support can vary by mode or session. Pro's cloud sandbox cannot
read local paths, and a GitHub link shows only what has been pushed. Unpublished
local edits need an authorized push or a Drive upload through the applicable
connector or skill, within that action's existing authorization. The Pro gate
is the only extra approval step.

Share only what the question needs. Prefer existing authorized GitHub or Drive
material, keep restricted items restricted, and do not create public links or
change sharing without authorization. Pin GitHub links to a commit so the
question and the evidence stay consistent.

## Research toolkit context

Scientific bootstrap and research-toolkit activation guidance is already supplied
in Pro's system instructions. Never repeat it in consultation prompts, including
bootstrap versions or Drive links, download/extraction paths, and installation
steps. Submit the actual question and relevant task evidence; let Pro use its
existing tooling instructions. Do not read local activation text merely to
reinsert it into a submission.

## Native app messaging (preferred)

Use the current `codex-app-tools` tools when they are supplied by the desktop
app. [ChatGPT app tools](chatgpt-app-tools.md) records the tested behavior and
the boundaries between ChatGPT, ChatGPT Work, Codex, and standalone CLI access.

- Identify the approved ChatGPT conversation with `list_threads` or its known
  ID, and confirm its backing kind is `chatgpt`. Preserve the source title.
  A title containing "Pro" and a paid account do not prove the selected model.
- Establish Pro selection for that exact chat from a supported current source
  or an explicit user-established selection. Use the browser only to inspect
  or set the mode when needed. The native sender does not expose a ChatGPT
  model selector: its `model` and `thinking` arguments affect Codex threads only.
  If selection cannot be established, report the limitation before sending.
- After approval of the actual question and materials, call
  `mcp__codex_app__send_message_to_thread({threadId, prompt})` once, omitting
  Codex-only overrides. It sends a normal user-visible prompt to ChatGPT using
  that conversation's current settings. No web composer or separate API billing
  is required for this submission route.
- Record successful acceptance and return control. Do not use `read_thread`,
  browser refreshes, `wait_threads`, or heartbeats to watch Pro finish.
- On the user's readiness signal, call `mcp__codex_app__read_thread` with the
  recorded ID. A useful initial text cap is `maxOutputCharsPerItem: 20000`;
  follow returned cursors and inspect truncation rather than treating that cap
  as a guarantee of completeness. Native reads can be stale. If the reported
  answer is missing or old, inspect the web conversation once instead of
  repeatedly polling the native reader or resending the question.
- The native sender was exercised end-to-end with an Instant test chat on
  2026-10-19. Pro was intentionally not used for that test. Applying this route
  to Pro follows the tool's existing-chat/current-settings contract; do not
  describe it as a completed live Pro test.

## Browser setup and fallback

Use the current Chrome computer-use connector (`mcp__cua_repl`) and follow the
documentation it returns. Start from its available entry point
(`getState`, `getTab`, `createBrowserTab`, or whatever it currently exposes), and
take tab IDs, selectors, and model names from the live UI.

- Confirm Pro is the selected model before sending; a paid plan alone does not
  establish the mode.
- Preserve the user's other conversations and drafts.
- Prefer native tools for supported operations and supported UI interactions
  for the remainder. Do not extract cookies or tokens, call private ChatGPT
  endpoints, or bypass desktop socket authorization.
- If a send looks ambiguous, inspect the current tab or the matching recent
  conversation in the live UI before retrying. If it was accepted, record it
  and return control. If it was demonstrably not sent, retry the identical
  approved submission without asking again. If delivery remains uncertain,
  do not resend: report that uncertainty and ask the user how to proceed.
  Resolving delivery ambiguity is not permission to monitor completion.
- Tabs may not survive; rely on the recorded URL and any tab-preservation method
  the connector documents, not invented ones.
- If Pro is unavailable, stop and tell the user. Never substitute a Codex chat,
  another model, or API billing.

## Status

Preferences above (professor framing, approval gate, fire-and-forget,
consolidation) come from the user. Quota and timing depend on the actual account. The
native send/read and browser create/delete findings are recorded with their
verification limits in [chatgpt-app-tools.md](chatgpt-app-tools.md). No live Pro
submission was made in the 2026-10-19 test. This transport change preserves the
existing approval gate and user-triggered retrieval protocol.

---
name: delegation
description: Delegate authorized work to Claude Code or Codex agents (native subagents or separate CLI workers), consult ChatGPT Pro through native app messaging when available, or create detailed technical infographics through ChatGPT web with Extra High, never Pro. Use for substantial implementation, UI checks, audits, documentation, refactoring, annotation batches, independent review, difficult research, complex module design, and infographic images. Claude receives bounded assignments; Pro receives questions with approval before each submission and user-triggered retrieval; infographic briefs put content before aesthetics. Includes context sharing, progress reporting, Claude allowances and reset times, scheduled continuation, and parent verification.
---

# Delegation

Conserve the parent Codex agent's tokens and context while maintaining quality. Prioritize useful delegation and verified results over minimizing elapsed time alone. Keep task ownership, consequential decisions, integration, and final verification with the parent.

Handle work in the current agent by default. Launch additional workers only with explicit user authorization, agreeing on agent count, provider, model and reasoning effort first. Approval covers only that delegation; extra agents or higher settings require fresh approval. Within those bounds, use the atomic-context policy below to choose useful assignments and propose worthwhile Pro consultations. This skill does not override user or repository restrictions on delegation, scope, or external data access.

## Organize work by atomic context

Prefer fewer agents with complete, relevant context. An **atomic context** is the smallest coherent question or workflow whose assumptions, evidence, and consequences need to be reasoned about together. It may span several modules or repositories. A file, module, phase, or individual finding is not automatically a useful delegation boundary.

- Keep related investigation, reproduction, correction, and follow-up with one context owner. Supply the relevant contracts, callers, data flow, shared assumptions, and evidence. Resume that worker when continuity helps; use a fresh context when independent scrutiny adds value. File ownership controls writes, not the scope of evidence an agent needs to understand.
- Propose additional agents **when beneficial**. Large batches can be useful when there are enough independent contexts, sufficient allowance, and capacity to integrate their results; agree on the count and settings before launch. The preference for fewer agents is a preference for coherent work, not an artificial ceiling on parallelism.
- Before adding a worker, identify the distinct result or uncertainty it will resolve. Weigh verified coverage, quality, and parent tokens saved against duplicated reading, handoff and integration effort, and allowance consumed. Handle small work directly or with deterministic tools when delegation adds more overhead than value.
- Avoid **productivity theater**: agent count, token volume, elaborate workflows, or consuming expiring quota are not measures of success. Do not mechanically create one agent per module or finding, repeat whole-repository exploration, or commission redundant reviews without a specific reason. For large audits, consolidate overlapping findings and related verification before expanding the reviewer pool; reserve dedicated independent scrutiny for consequential or disputed conclusions.

For substantial batches, plan against current allowance and observed consumption, including capacity to verify, synthesize, and integrate the results. Expand or reduce later waves according to their usefulness. Keep an incremental report or usable artifact so a limit does not strand all value in unfinished investigations. Claude quota mechanics are in [claude-code.md](references/claude-code.md). Codex execution and account limits are separate; read [codex-cli.md](references/codex-cli.md) only for Codex work.

## Choose the relationship and target

| Target | Relationship | Suitable work |
| --- | --- | --- |
| **ChatGPT web · Extra High** | Commission one or more infographic images | Detailed explanations of modules, packages, algorithms, and related technical systems. Supply all information to convey first, then aesthetic direction. **Never use Pro for this route.** |
| **ChatGPT Pro** | Consult a professor or expert colleague | Difficult mathematical or algorithmic questions, literature synthesis, adversarial reasoning, optimization, rethinking an approach, and exceptionally difficult modules implemented from scratch through sustained investigation and testing. |
| **Codex native subagents** | Give bounded work within this chat | Use when Codex is selected and the current collaboration tools fit; retain native session limits and execution policy. |
| **Codex CLI workers** | Run independent durable local sessions | Use when separate Codex CLI workers are requested or authorized; pin the selected model/effort and ChatGPT login, with disjoint ownership and exact resume. |
| **Claude Opus 5.5** | Give a capable worker a bounded assignment | Default for substantial implementation, reproducible bug investigations, UI inspection, long audits, documentation, refactoring, and routine independent reviews. |
| **Claude Fable 5.1** | Request demanding independent scrutiny | Mathematical assumptions, architecture, counterexamples, and subtle correctness reviews of parent or worker output. Use directly when warranted; an Opus pass is not a prerequisite. |
| **Claude Sonnet 5** | Distribute specified, independent batches | Tests, adapter migrations, view audits, and documentation reconciliation with clear scope and affordable checks. |
| **Claude Haiku 4.5** | Process well-specified batches | First-pass image/text annotation with a rubric and abstention, structured extraction, inventories, and record normalization. Use deterministic code when sufficient. |

Routing reflects the user's working preferences, not a universal capability ranking. A Pro consultation need not follow a failed Claude attempt. Fable remains valuable for a focused, rigorous independent review; choose Pro when open-ended inquiry or unusually deep sustained work is the point.

Read only the relevant operating guide:

- **Claude execution or usage:** [claude-code.md](references/claude-code.md). It links to model evidence/examples and detailed operational troubleshooting. `scripts/worker.py` and `scripts/usage.py` operate Claude workers only.
- **Codex native or CLI workers:** [codex-cli.md](references/codex-cli.md), covering provider choice, compatible CLI/auth, effective model/effort, separate sessions, durable invocation records, exact resumes, approval handling and accounting. `scripts/codex_worker.py` runs owned Codex CLI invocations.
- **ChatGPT Pro consultation:** [chatgpt-pro.md](references/chatgpt-pro.md), covering question framing, native app messaging, browser setup/fallback, GitHub/Drive, submission approval, and user-triggered retrieval.
- **ChatGPT conversation access or CLI/app interoperability:** [chatgpt-app-tools.md](references/chatgpt-app-tools.md), covering retrieval of older and archived chats, native list/read/send, model selection, creation/deletion boundaries, Markdown exports, stale reads, and the protected desktop bridge.
- **Technical infographic images:** [chatgpt-infographics.md](references/chatgpt-infographics.md), covering ChatGPT web with Extra High, content-first image briefs, coordinated image series, and visual verification. This is a user-preferred option when detailed infographic images suit the task.

Claude remains the default worker provider unless the user or task selects Codex. Preserve an explicit provider choice. Codex CLI is an available separate-session route when authorized; it does not waive account, sandbox, data or spending limits. The helper disables recursive delegation; a separately authorized CLI coordinator requires its own bounded policy.

Do not route a Pro consultation through the Claude runner, substitute an API call for the user's ChatGPT subscription, or create user-owned Codex chats to run Claude workers. Claude workers are external CLI processes. Do not silently substitute native Codex subagents for the named provider; that would consume the Codex capacity this workflow is intended to conserve.

For an existing ChatGPT conversation with Pro already selected, prefer native `mcp__codex_app__send_message_to_thread` over browser submission; retrieve text with `read_thread` after the user signals readiness. Browser interaction is a setup or fallback route, not a prerequisite for asking Pro questions. ChatGPT model selection must be established for that exact chat: the messaging tool's `model` and `thinking` overrides apply only to Codex. Read the linked guides for capability and freshness limits.

## End the turn and resume when useful

The Codex app can schedule follow-ups in this same chat through `mcp__codex_app__automation_update` with `kind: "heartbeat"`. Check the tools supplied in the current context first; this is an available orchestration option, not something to rediscover for each wait. When an authorized workflow is waiting on a long Claude or Codex job or an allowance reset and no useful independent work remains, use scheduled continuation when it saves parent attention and usage. Short waits can stay in the active turn.

- Save a durable checkpoint: objective, relevant paths and revisions, owned worker run directories, completed work, the condition to check, and the exact next action. Confirm that any running job survives the end of the turn; saved status files alone do not establish process durability. Resumed work uses the permissions then available, not an assumption that turn-scoped grants persist.
- Use the current chat's heartbeat, reusing a matching follow-up when present. Choose a useful cadence or the known reset time rather than frequent speculative checks. Confirm that scheduling succeeded before ending the turn, and tell the user what will cause work to continue. If the tool is unavailable or fails, do not claim an automatic return is arranged. Follow the tool's current schema; do not invent automation directives or substitute a standalone cron job for a chat follow-up.
- The saved prompt should check actual worker status or refreshed allowance, continue only when the condition is satisfied, and otherwise stay quiet unless a failure or required user action appears. On completion or cancellation, remove or disable the follow-up. These are scheduled checks, not arbitrary instant event triggers; each run consumes usage. Local continuation requires the machine and app to remain available.

**Pro remains the exception:** its answer is retrieved only after the user says it is ready. Do not schedule Pro checks or change its approval and fire-and-forget protocol through this general continuation policy.

## Preserve the distinction

**Claude:** define the objective, inputs, owned files, constraints, and a concrete output with an affordable verification step. UI checks and long audits should return compact findings supported by local evidence, avoiding a second exhaustive parent pass.

**Codex:** define the same concrete worker contract, preserving the chosen model and effort. Prefer native subagents for suitable current-chat subtasks; use an authorized independent CLI session when requested or needed for its lifecycle. Verify effective native records, actual owned processes and exact-session continuity. A configured limit, zero exit code or saved state file alone does not prove admission, durability or correctness.

**Infographics:** use ChatGPT web with **Extra High**, never Pro. Explicitly ask it to generate an image or a coherent series of images. Give the complete technical content before aesthetic details; check the rendered result against the source. Pro's special submission gate and fire-and-forget protocol are specific to Pro and do not automatically apply to this route.

**Pro:** start from a genuinely difficult unresolved question and the consequential choice its answer will inform. The parent is accountable for asking incisive, specific questions that reach beyond routine advice. Artifact format is secondary to answering the question. Supply known facts, competing approaches, assumptions and constraints, while leaving room to challenge the framing. For a coherent research problem, prepare one initial brief that gives Pro ownership of the complete investigation and the authorized evidence needed to carry it through. Follow the question-quality guidance and worked example in [chatgpt-pro.md](references/chatgpt-pro.md); do not turn the consultation into a worker checklist or a predetermined verdict.

For genuinely independent review, use a fresh context. Give the requirements, artifacts, relevant assumptions, and essential rationale without an expected conclusion or the implementer's self-assessment. In a collaborative Pro consultation, sharing our tentative reasoning and uncertainty is helpful; do not confuse that dialogue with a blind review.

## Pro approval and fire-and-forget protocol

The user explicitly requires approval before each Pro submission, including follow-up questions. Broad delegation authorization does not waive this specific rule. Prepare the actual question and artifact links first, explain what you propose to ask, and let the user approve that concrete submission. Do not resubmit or replace an already-approved question with a materially different one without approval. Do not ask again for the same submission whose exact question and materials are already approved.

After approval, send once through the native app tool when available, confirm that the submission was accepted, preserve the conversation ID/URL and input snapshot, and tell the user it was sent. Acceptance is not response completion. **Never wait for Pro's answer, poll for completion, schedule monitoring, or send progress prompts.** Continue independent authorized work or return control. The user will tell you when the answer is ready; that is the trigger to retrieve and review it, preferably through the native reader. Any subsequent message to Pro requires its own approval. Follow an explicit later change to this protocol if the user makes one.

This approval is a user instruction, not an inferred skill precaution. When requesting it, quote the rule "approval before each Pro submission," name and link this skill, and briefly explain its source; for example, "As you requested, I need your approval before sending this question to Pro". Asking for permission belongs in the available question tool or a final response, not an intermediate commentary question.

## Shared context and authority

Read the artifact that defines the real scope before preparing a handoff. Use relevant files and evidence rather than whole conversation dumps. Claude and Codex workers can read explicitly scoped local paths. Pro can receive accessible GitHub links and Drive materials; a local path alone is not available in its sandbox. Identify the source revision, including any uncommitted work supplied separately.

When earlier research or decisions live in an old ChatGPT conversation, retrieve the existing messages through native `list_threads`/`read_thread`, or discover archived ChatGPT chats with `list_archived_threads` and `source: "chatgpt"`. This does not send a new prompt or ask the original model to summarize. Read older pages and check truncation/freshness before claiming completeness; the recent-chat inventory is not a full-account search. Follow [the historical retrieval guide](references/chatgpt-app-tools.md#older-and-archived-conversations) for lookup and Markdown export. An explicit request to retrieve a completed historical chat is sufficient to read it; it does not waive the no-polling rule for a still-running Pro consultation.

Keep task materials in authorized destinations with appropriate existing visibility. Delegation does not authorize new public sharing, production actions, account changes, spending, unrelated edits, or access beyond the parent task. Follow existing authorization for those actions rather than repeatedly asking; the per-submission Pro approval above remains required. The parent owns consequential decisions and whether to act on delegated advice.

Keep briefs, transcripts, and run records outside published source unless the user wants them included. Use explicit file ownership or isolated checkouts for simultaneous worker edits. For Pro, preserve the exact conversation link and input snapshot so later dialogue addresses the same work.

## Keep the user informed

Report delegation in ordinary commentary, briefly and specifically:

- **Claude or Codex launch:** identify the provider, actual model/effort, its assignment, and what the parent retains. For a batch, use a compact combined update.
- **Worker progress:** inspect actual status and include it in meaningful updates, at least every few minutes while the parent is actively working alongside running workers. If continuation is scheduled, report the condition and cadence before ending the turn, then report meaningful changes on later runs. Do not invent percentages or completion estimates.
- **Worker return:** identify the provider, model and assignment, summarize useful results, and say whether they await review, are verified, need correction, or are blocked. Combine near-simultaneous returns.
- **Infographics:** identify ChatGPT web with Extra High and the subject before submitting. Report actual progress when relevant, then present the returned images and what was checked or still needs correction. Do not call this a Pro consultation.
- **Pro:** request approval through the question tool or final response as described above; after approval, confirm sending with the conversation link, then return control or continue independent work without monitoring. When the user returns, summarize the answer and the parent's assessment after retrieving it.
- **Completion:** say what was delegated, what the parent verified, and any remaining limitation. If a Pro answer is pending, state that the user will signal when it is ready. Do not imply the consultation is finished or automatically monitored.

Do not dump raw logs, token streams, or unchanged polls into the conversation. Report permission failures or unavailable capabilities when they materially affect the work. Do not silently leave Claude or Codex workers active after reporting their work complete.

## Verify and integrate

A worker's successful exit or a completed Pro response is not proof of correctness. Start with the answer, artifacts or diff, and targeted evidence. Read full transcripts only when uncertainty, failure, or a consequential claim warrants it. Agreement between models alone is not proof. Do not constrain Pro's investigation merely to shorten its answer; conserve parent context by keeping detailed evidence in durable artifacts and reviewing selectively.

Validate at the real failure surface: rendered UI, executable behavior, source-grounded literature claims, annotation IDs and labels, or independently reproduced mathematical examples. Independently check critical claims and changed behavior; sample lower-risk audit/documentation findings rather than repeating an entire sweep. Expand checks when discrepancies appear.

Challenge unsupported conclusions, whether from Claude, Codex or Pro. Follow up with concrete evidence and questions when needed, respecting Pro's approval gate. Integrate only reviewed, in-scope work while preserving unrelated changes. Record what was actually checked and acknowledge unresolved uncertainty.

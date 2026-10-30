# ax chat and VS Code audit remediation — 0.2.0

This is the finding-to-fix-to-evidence ledger for the two October 29 audits. The
implementation runs in the shared UI and provider adapters. Model-backed tests and
native-editor tests are recorded separately from fixture tests. A passing demo does
not establish successful live sending or handoff.

## Audited defects

| Finding | Fix | Regression evidence |
| --- | --- | --- |
| Duplicate titles can select the wrong chat | Custom readonly editors use `ax-session:` URIs containing server, provider and session ID; legacy serializer migrates its exact identity and editor column | `vscode/src/sessionUri.test.ts`; native smoke below |
| Concurrent opens create duplicate drivers | Single-flight startup futures plus an interprocess writer lease; initialization failures close the child | `tests/test_chat_regressions.py` concurrent open; fake-driver lifecycle suite |
| Failed takeover loses queued input | Private SQLite outbox; transactional claims and retryable startup failure | `test_failed_takeover_is_retryable_and_reads_do_not_consume_it` |
| Ownership lookup failures imply closed | Tri-state external ownership; unknown cannot acquire, only confirmed foreign ownership yields | Unknown ownership and inventory regression tests |
| Claude desktop registration inherits unrelated settings | Register the held driver's confirmed configuration; preserve existing app records; show failure | `tests/test_claude_app.py`; registration regression |
| Wrong Codex permission approval shape | Separate method-specific permission, command, file and MCP responses; bounded permission subset and scope | Permission response regression; JSON Schema validation |
| File approvals omit proposed changes | Correlate request and item, show provider patches or generated tool-input diff; explicit missing-patch label | `ui/src/lib/approval.test.ts`; provider request regressions |
| Multiple approvals orphan requests | ID/kind keyed request map; out-of-order answers; compatibility singular heads | Parallel approval regression; `pending-requests.tsx` |
| MCP elicitation rejected | Schema-driven typed forms and URL confirmation with accept/decline/cancel; invalid replies remain pending | MCP backend validation; behavioral array form test |
| Tab closure loses drafts | IndexedDB browser drafts and private extension storage; separate pending snapshot and stable message ID | `ui/src/blocks/composer.behavior.test.tsx` |
| Late submit ACK clears new typing | Submission detaches the old draft, and ACK removes only its ID | Behavioral late-ACK/reopen and failed retry tests |
| Same-named files silently collide | Canonical path/range identity, disambiguating path chips, and fresh text when reattaching an unsaved selection | `plus.test.ts`; keyboard context behavior test |
| Completed tools inaccessible | Expandable completed entries with full paginated output, recorded exit status/timing | Long tool output regression; history UI |
| History capped at 300; Find unavailable | Backward pagination, full-source search, earlier result pages and Cmd/Ctrl+F focus | 725-event pagination and late-tool evidence tests |
| Changes appear complete when history is partial | Persistent provider-history coverage; separate full Git workspace comparison | `tests/test_restore_regressions.py`; change-review UI |
| Slash command discovery misleads | Executable commands separate from skills; reserved exact commands available while discovery loads | `tests/test_commands.py`; slash tests |
| Default effort reset ignored; effort carries across models | Explicit null clears override; validate model/effort pair together | Invalid effort and model switch regression; model picker tests |
| Claude rejects setting but UI claims it applied | Requested/pending/effective states; rejected controls retain confirmed values; defer process restart | Rejected settings regression; driver configuration suite |
| Terminal errors disappear | Persist bounded failure evidence and diagnostics after dead driver cleanup | Retained authentication error regression |
| Streaming concatenates completed items | Track item/turn identity; clear completed partial items; merge transcript identity | Streaming duplication regression |
| Steer resets this-turn diff | Use provider turn IDs/lifecycle boundaries | Steering boundary regression |
| Refresh multiplies polling chains | Shared session feed; one request/timer, coalesced refresh; serial earlier reads; hidden transcript suspension | Controlled-timer `session-feed.test.ts` |
| Provider outages appear as empty inventory | Per-provider inventory errors alongside healthy sessions; explicit unavailable selection recovery | Model availability tests; panel rendering tests |
| Gallery focus escapes behind overlay | Existing dialog primitive supplies focus trap, Escape, isolation and focus return | Behavioral `pictures.test.tsx` |

## Workflow completion

| Stage | Delivered behavior | Evidence/location |
| --- | --- | --- |
| 1 | URI identity, legacy migration, serialized/locked startup, tri-state ownership, confirmed registration | `chat.py`, `claude_app.py`, `vscode/src/extension.ts` |
| 2 | Durable ordered outbox with stable IDs, atomic claim, edit/cancel/retry and uncertain reconciliation; durable drafts and idempotent new-chat starts; explicit Queue | `chat_store.py`; start-ID/outbox regressions; pending-message behavior test |
| 3 | Multiple approvals/questions; structured permission decisions, tool input edits, proposed changes, MCP forms/URL flows; stale answers rejected and turn/process reconciliation | `chat_requests.py`, request components; fake provider protocol tests |
| 4 | Effective/pending settings, supported effort reset, retained errors and diagnostics, item streaming, provider-specific failure states and available new-chat defaults | Driver regressions and model tests |
| 5 | Full history/search, incremental tool output, single refresh coordinator, hidden-tab pause, dialog gallery, persisted scroll/tool expansion/search query | `live_sessions.py`, `session-feed.ts`, `view-state.ts`, history components |
| 6 | Keyboard @file/folder/range completion; configurable current file/unsaved selection chips; explicit terminal/Problems attachments; inline/multi-file/hunk feedback; Git staged/unstaged/untracked changes; syntax highlighting/copy; provider-history restore preview and revision checks | `editor.ts`, context/review blocks; Git/restore conflict tests; Markdown tests |
| 7 | Rename, archive/unarchive, pin, group/filter/order; fork, restore, fork-and-restore; compact/review/history/session commands; real context usage or unknown; capability catalogs, supported management and native handoff; keyboard/font/review preferences | `session_ops.py`, `commands.py`, shared session actions/preferences; SDK disk-only fork test |

## Coverage and provider boundaries

- Restore and turn/session comparisons use provider history exclusively. Claude's
  checkpoint coverage and Codex's recorded patches do not cover shell-only writes.
  Missing/conflicting files are disclosed and excluded. Each selected restore is
  previewed and all selected revisions are checked before writing. Rename pairs must
  be selected together, recreated deleted files are refused, and an I/O failure rolls
  earlier writes back when no other writer has changed them. Claude files with no
  original backup and no explicit provider creation record are excluded. Original chats
  survive a fork. No recurring ax file snapshots are introduced.
- The Git comparison deliberately covers the entire workspace since HEAD, including
  staged, unstaged and nonignored untracked paths, and may contain unrelated work.
  Renames/deletions appear as their affected paths. Binary or unreadable files have
  explicit skipped reasons. Review comments are sent only by the explicit send action.
- An external Codex app owner accepts queued input. ax labels this Queue and offers
  handoff. Claude cannot accept live steering from ax while another client owns it.
- Claude compaction uses its documented `/compact` prompt command; review uses an
  explicit review prompt. Codex uses app-server compact/review operations. Context
  usage/window values stay unknown unless the running provider reports them.
- MCP elicitation forms are supported for exposed Codex requests. The installed
  Claude stream protocol does not expose a documented elicitation request subtype;
  complete provider-only authorization in its native client. Unknown controls are
  never treated as an approved request.
- Codex skill configuration, MCP reload/OAuth and Claude plugin enable/disable use
  supported interfaces. Provider-exclusive app/plugin management has a native
  handoff. No production dependency on Codex under-development plugin RPCs.
- Closing a driver clears its in-memory requests because no provider can accept
  those IDs after process exit. Reloading the UI retains requests in the live driver.
  Ambiguous input delivery remains visible and never retries automatically.
- A crash before a new-session ID is durably recorded leaves that start ID blocked
  for reconciliation; ax does not risk silently creating a second conversation.

References: [VS Code custom tab identity](https://code.visualstudio.com/api/references/vscode-api#TabInputCustom),
[Claude SDK commands](https://code.claude.com/docs/en/agent-sdk/slash-commands),
[Claude checkpoint limits](https://code.claude.com/docs/en/agent-sdk/file-checkpointing#limitations),
[Codex app-server API](https://learn.chatgpt.com/docs/app-server#api-overview).

## Validation record

Local regression checks, builds, visual checks, packaging, native-editor checks and
live provider checks have distinct entries. Final results are filled in after each
run. Initial full Python pass: 1,137 passed, one skipped; the stale UI build and three
inherited-session environment failures were identified for rebuild/isolation.
Last full Python suite: **1,159 passed, one skipped, one unchanged date-sensitive failure**
(`test_digest.py::test_the_start_hook_prints_context_for_the_tool_and_never_fails`).
That test passes when its clock is fixed to its fixture date, October 25. The source
and test are byte-for-byte unchanged from the implementation baseline. Ruff passes
on `src/` and `tests/`. Final focused history/restore checks also pass (29 tests), including
ambiguous inverse-hunk refusal and both providers' steering boundaries. Repository-wide Ruff reports ten pre-existing issues in three
untouched `skills/delegation/scripts/` files.

Final UI verification: **233 tests passed**. Extension verification: **78 tests passed**.
Both type checks, the theme/color check, the web build, the webview build and the
extension bundle pass. The visual check passes all 48 light/dark desktop, 480-pixel
column and phone pages; light-mode screenshots were inspected before dark mode.

The installed 0.2.0 VSIX passed native editor checks with same-title chats in three
columns, close/reopen, real window reload, identity exposed before content restore,
and legacy tab migration preserving its draft and column, including an identity
already open in another column. The final result is in
this chat's `work/ax-validation/native-final.json`. The regression harness is
`vscode/scripts/native-smoke.cjs`: install it as the main file of a disposable helper
extension with `onStartupFinished` activation. Set `AX_SMOKE_PROFILE` to its disposable
VS Code user-data directory, optionally `AX_SMOKE_SERVER`, `AX_SMOKE_PHASE` and
`AX_SMOKE_OUTPUT`. It refuses non-demo session IDs, reloads once, and writes a JSON
result. Use normal installed-extension mode; VS Code's extension-test mode uses
memory-only storage and cannot validate reload persistence.

Live approval: exactly two test chats, GPT-6-Luna at low effort and Claude Haiku 5.5
at low effort, no more than six short turns each, no delegated workers or extra-usage
credits. User approved this configuration during implementation. **Both passed**, with six
inputs each and native transcript evidence for start, steer, queued delivery,
handoff/reconnect, process exit, retained error and restart. Claude's desktop record
was registered with its confirmed settings. Runtime models were `gpt-6-luna` and
`claude-haiku-5-5`. Shutdown left zero held drivers. Codex's credit balance was unchanged;
post-check allowances remained within ordinary usage. No further model-backed tests
were launched. Evidence is in this chat's `work/ax-validation/live.json` and
`allowance-after.json`. Native app focus/automatic ownership yielding and real MCP
elicitation were covered by protocol fixtures rather than additional model turns.

## Migration and rollout

1. Update the backend's environment from the 0.2.0 project/lockfile; it now needs
   `claude-agent-sdk` and `jsonschema`. A VSIX alone cannot upgrade a running ax server.
   Stop and restart that server only after its current sessions have been handed back.
2. Preserve the old VSIX and backend environment/version before installing 0.2.0.
   Package and validate using `npm --prefix ui run verify`, `npm --prefix ui run build`,
   `npm --prefix ui run check`, `npm --prefix vscode run verify`, and
   `npm --prefix vscode run package`.
3. Existing webview tabs migrate through their serialized provider/session identity
   into custom-editor resources. Titles are never matched. Existing draft storage is
   retained. Each resource remains bound to its original server address. Drafts that
   pre-0.2.0 versions held only in iframe memory cannot be recovered after that iframe
   is destroyed: copy those drafts before upgrading. Serialized legacy drafts migrate
   automatically; this case is included in the native reload check.
4. `chat.db` is separate from provider transcripts and the archive. Schema setup is
   idempotent and adds missing columns without dropping rows. Legacy singular
   approval/question and other API fields remain for old clients.
5. Install into an isolated VS Code profile first. Verify restoration with duplicate
   titles, draft close/reopen, hidden tabs, three editor columns, and light/dark modes.
6. Release only after the ledger has passing evidence or the user has accepted the
   disclosed provider boundary. The work does not automatically install into the
   user's working profile, restart their real server, commit, or push.

## Rollback

Hand back the test sessions and close the new backend before downgrading. Reinstall
the previous VSIX/backend environment. Keep `chat.db`, provider transcripts, extension
`globalStorage` draft files and browser IndexedDB intact; older clients can ignore
new fields. Do not delete uncertain outbox rows to make rollback appear successful.
Before restarting a downgraded server, inspect its pending queue so it cannot race the
new dispatcher. The implementation baseline archive in this chat's work directory
preserves pre-existing dirty source and can be used for a scoped comparison; never
reset the repository wholesale.

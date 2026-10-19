# ChatGPT conversations through the desktop app

Use this reference for native ChatGPT conversation access, Pro transport,
conversation exports, and the boundary between desktop tools and the Codex CLI.
Discover the currently supplied tools and use their actual schemas. These
findings describe the 2026-10-19 local installation, not a general public
ChatGPT history API or a promise about other builds.

## Capabilities and evidence

| Operation | Native app surface | Evidence and limits |
| --- | --- | --- |
| Discover conversations | `mcp__codex_app__list_threads` | Verified inventory includes `kind: "chatgpt"` and `kind: "codex"`. Recent and pinned lists do not prove full account coverage. Use source titles verbatim. |
| Read ChatGPT text | `mcp__codex_app__read_thread` | Verified actual user/assistant messages. A 500-character cap truncated one answer; 20000 recovered its 4505-character text. Check freshness, cursors, and truncation. |
| Send a prompt to an existing ChatGPT chat | `mcp__codex_app__send_message_to_thread` | Verified end-to-end: the native prompt produced "Received." in an Instant chat. Uses the chat's current settings. |
| Select a ChatGPT model or effort | No selector in the native sender | `model` and `thinking` overrides apply only to Codex. Establish the intended ChatGPT mode separately; never infer it from subscription or title. |
| Create an ordinary ChatGPT Chat conversation | No ordinary Chat target in the current `create_thread` schema | Verified through the web UI. A new empty web chat acquired a stable conversation ID after its first prompt; native follow-up then worked. |
| Create a ChatGPT Work cloud task | `create_thread` with `target.type: "chatgptWorkCloud"` | Exposed by the schema, not exercised in this test. Requires an explicit user request for a ChatGPT cloud Work task. It is distinct from ordinary Chat and cannot be assumed to select Pro. |
| Delete an ordinary ChatGPT chat | No deletion tool in the supplied native app catalog | Web deletion was verified: the disposable chat's old URL became inaccessible. Do not confuse absence of a native delete tool with inability to delete ChatGPT chats. |
| Rename/archive/list archives | `set_thread_title`, `set_thread_archived`, `list_archived_threads` | Exposed by the tools, not exercised here. Use the ChatGPT source where required and follow current restore limitations. Archiving is not deletion. |

The send test used Instant for both prompts, not Pro. The original default
model preference was restored afterward. Native reads of the same chat still
returned the earlier "Ready." turn after the web UI displayed the native test
message and "Received." response. Treat this as observed stale-read behavior;
the native reader and inventory are not guaranteed live event streams.

## Older and archived conversations

Retrieve earlier ChatGPT discussions when the user asks for them or when their
existing research or decisions are relevant to an authorized handoff. Use the
recorded conversation ID/URL when available; a chat need not be open to read it.
Retrieval reads stored messages without submitting a new question, waking the
original expensive model, or asking it to summarize its history.

1. For an active historical chat, inspect `list_threads`, keeping ChatGPT entries
   distinct from Codex entries through `kind`. Use the exact source title in
   user-facing references. The tool exposes a recent-list limit, not a complete
   full-text search or a cursor for all active chats. If it is missing, use a
   larger supported limit, an already-known URL/ID, or supported app/web search;
   absence from the returned recent list does not establish deletion.
2. For archived ChatGPT chats, use the local desktop's
   `mcp__codex_app__list_archived_threads({source: "chatgpt", limit: 25})`,
   omit `hostId`, and pass its returned `nextCursor` as `cursor` for another page
   when necessary. This capability is exposed by the schema but was not
   exercised in the live test. Do not assume native ChatGPT restore support.
3. Read the identified conversation with `read_thread`. Its initial page
   contains recent turns; pass the returned cursor to retrieve older turns.
   Check `hasMore`, truncation, and the expected dates/messages. An old chat may
   be readable even if it did not appear in the recent sidebar inventory.
4. Return or save the requested source text and ID/URL. Extract relevant prior
   decisions with message provenance when preparing a handoff. Ordinary code
   can export Markdown as described below; summarization is a separate optional
   step and does not require the original Pro model.

Do not unarchive, rename, message, or delete a historical conversation merely to
read it. If a native read is inaccessible, stale, or incomplete, use the supported
web interface for the requested retrieval or report the specific missing
coverage. A request to retrieve an old completed chat needs no new Pro submission
approval. A still-running consultation retains its user-triggered retrieval rule.

## Preferred Pro transport

For an approved existing ChatGPT conversation with Pro selected, send directly:

```javascript
await tools.mcp__codex_app__send_message_to_thread({
  threadId: approvedChatId,
  prompt: approvedQuestion,
});
```

There is no need to use the web composer just to ask Pro a question. A browser
may still be needed to create an ordinary Chat conversation, establish its
model selection, upload or retrieve files, or inspect a stale/incomplete result.
The native tool contract preserves existing ChatGPT settings; a live Pro send
was intentionally not exercised. Do not pass `model: "pro"` or a Codex model
to try to select Pro in ChatGPT.

The user's [Pro protocol](chatgpt-pro.md) still applies: exact-submission approval,
send once, record acceptance and the conversation ID/URL, then return control.
Retrieve only when the user says it is ready. Changing transport does not
authorize completion polling, extra messages, new conversations, or cleanup.

If acceptance is uncertain, resolve only the delivery question through one
appropriate supported read or UI inspection. Do not duplicate an accepted
prompt merely because a native reader is stale. If delivery remains uncertain,
report it and ask how to proceed. This is not permission to wait for Pro's answer.

## Retrieval and local Markdown

On an authorized retrieval, the native reader can return actual text without
asking the original expensive model to summarize itself:

```javascript
await tools.mcp__codex_app__read_thread({
  threadId: approvedChatId,
  turnLimit: 10,
  includeOutputs: false,
  maxOutputCharsPerItem: 20000,
});
```

Inspect `page.hasMore`, `page.nextCursor`, per-item truncation, timestamps, and
whether the expected message is present. Preserve chronological order when
combining newest-first pages. Parse structured user content as well as assistant
text; do not silently discard non-text items. Label unavailable attachments or
branches rather than claiming a complete archive. Long-history pagination,
branch coverage, attachment export, and full-account enumeration were not
validated in this test.

A deterministic exporter can write Markdown with provider, conversation ID/URL,
source title, timestamps, roles, and exported-through turn/message IDs. It does
not need per-conversation model inference. A compact handoff or semantic map is
a separate optional inference step. Keep original provider stores authoritative
and export to a separate vault; no session-directory relocation or complete
sync service was implemented or validated here.

## CLI and programmatic boundary

The installed `codex-app-tools` plugin is an MCP server backed by a local desktop
socket, supplied via `CODEX_APP_TOOLS_PIPE_PATH`; calls also require caller
thread metadata. Its internal launch details are not a stable public API.
Do not copy transient socket paths or old conversation IDs into reusable code.

Read-only, model-free probes tried both the bundled MCP launcher directly and
the app's bundled Codex app-server with the MCP configured. Both reached the
desktop boundary and failed with `Codex app tools pipe closed`. The app log
reported `untrusted-code-signing-identity`. Native calls supplied to this chat
worked. These observations do not establish a working standalone Python or
terminal exporter, and they do not prove that every platform/build rejects one.

`codex app` is a launcher. The documented app-server method
`mcpServer/tool/call` can call a thread's configured MCP server, but it does not
grant access to the desktop's protected bridge. Starting `codex exec` adds a
model run and does not itself solve this authorization boundary. Do not launch
extra workers, disable identity checks, or extract cookies/tokens to get around it.
See the official [app-server API](https://learn.chatgpt.com/docs/app-server#api-overview)
and [Codex execution guide](codex-cli.md) for the separate CLI route.

The native `get_usage_limits` tool reports Codex account allowance. It is not a
ChatGPT Pro allowance reader or a Claude subscription meter.

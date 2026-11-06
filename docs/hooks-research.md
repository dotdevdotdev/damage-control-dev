# Claude Code hooks: research report

A survey of every Claude Code hook event, handler type, registration surface and condition, what each looked like when observed, and which of them damage control should use. Written for issue #48. It changes no engine code.

- [Scope and method](#scope-and-method)
- [Version baseline](#version-baseline)
- [The 33 events](#the-33-events)
- [Handler types and what happens when one fails](#handler-types-and-what-happens-when-one-fails)
- [How a decision resolves](#how-a-decision-resolves)
- [Registration surfaces](#registration-surfaces)
- [Conditions: `matcher` and `if`](#conditions-matcher-and-if)
- [Version history](#version-history)
- [Observation results](#observation-results)
- [Verdicts](#verdicts)
- [Proposed next batch](#proposed-next-batch)
- [Unverified](#unverified)
- [Reproducing the observations](#reproducing-the-observations)
- [Sources](#sources)
- [Appendix A: observed payloads](#appendix-a-observed-payloads)

## Scope and method

Three kinds of evidence, labelled throughout:

- **Documented**: stated in the official documentation or changelog (linked under [Sources](#sources)). Paraphrased here, never quoted.
- **Observed**: seen in a live `claude -p` run against Claude Code 2.1.319, in a scratch project, with a logging hook that wrote every payload to a file. About 80 handler/decision cases, 33 registration-surface cases, and one run per event that could be provoked.
- **Unverified**: documented or plausible but not seen. Listed again in [Unverified](#unverified); none of the verdicts below rests on an unverified claim without saying so.

Every observed run used a scratch working directory, a scratch `--settings` file, `--setting-sources project,local`, `--no-session-persistence`, and a debug log in the scratch directory. The harness is described in [Reproducing the observations](#reproducing-the-observations).

**Limits of this method.** `claude -p` is non-interactive. Anything that needs a person at a terminal (an interactive permission prompt, `/add-dir`, a teammate going idle, an MCP server asking for input) was not exercised, and is marked unverified. No run touched a user or managed settings file on purpose. Claude Code keeps session state under its home directory whatever flags it is given, so the runs were not hermetic: the sessions used the normal login (an isolated config directory lost authentication), and Claude Code wrote its own session-environment entries and, for plan-mode probes, plan files there. No settings or hook file in the home directory was written by the harness.

## Version baseline

| | Version |
|---|---|
| Engine floor for `onFailure: "block"` (`ONFAILURE_MIN_VERSION`) | 2.1.295 |
| Observed | 2.1.319 |
| Newest changelog entry read | 2.1.318 |

Documented behaviour below is the current documentation; where the changelog dates a feature, the version is given. Observed behaviour is 2.1.319 only. A behaviour observed here may differ on 2.1.295.

## The 33 events

Fired column: **O** = payload observed live; **D** = documented only (unverified). "Can block" is what the documentation says the event's decision control allows; the engine registers hooks only where blocking or auditing a tool call is the point.

| Event | Fires when | Matcher filters | Can block | Fired |
|---|---|---|---|---|
| `Setup` | `--init-only`, or `--init`/`--maintenance` with `-p` | the flag | no | O |
| `SessionStart` | session begins, resumes, clears, compacts | `startup`, `resume`, `clear`, `compact`, `fork` | no | O (startup, clear, compact); resume and fork D |
| `UserPromptSubmit` | a prompt is submitted; also turns Claude Code starts itself | none | yes (documented) | O |
| `UserPromptExpansion` | a typed command or skill expands into a prompt | command name | yes (documented) | O |
| `PreToolUse` | before a tool call | tool name | yes | O |
| `PermissionRequest` | a tool call needs a permission decision | tool name | yes (deny) | O |
| `PermissionDenied` | auto mode denies a call | tool name | no (can say retry) | D |
| `PostToolUse` | a tool call succeeded | tool name | feedback only | O |
| `PostToolUseFailure` | a tool call failed | tool name | feedback only | O |
| `PostToolBatch` | a parallel batch of calls resolved | none | feedback only | O |
| `Notification` | Claude Code sends a notification | notification type | no | D |
| `MessageDisplay` | assistant text is displayed | none | no (transform or hide) | O |
| `SubagentStart` | a subagent spawns | agent type | no | O |
| `SubagentStop` | a subagent finishes | agent type | yes (keep going) | O |
| `TaskCreated` | `TaskCreate` runs | none | yes (documented) | O |
| `TaskCompleted` | a task is marked complete | none | yes (documented) | O |
| `Stop` | Claude finishes responding | none | yes (keep going) | O |
| `StopFailure` | the turn ends on an API error | error type | no | D |
| `TeammateIdle` | an agent-team teammate goes idle | none | yes (documented) | D |
| `InstructionsLoaded` | a `CLAUDE.md` or rules file is loaded | load reason | no | O (`session_start`, `nested_traversal`) |
| `ConfigChange` | a settings or skill file changes | source | yes, except policy | O (`project_settings`, `local_settings`, `skills`) |
| `CwdChanged` | the working directory changes | none | no | O |
| `DirectoryAdded` | `/add-dir` or the SDK adds a directory | how it was added | no | D |
| `FileChanged` | a watched file changes | literal filenames | no | O |
| `WorktreeCreate` | a worktree is being created; replaces git | none | yes (failure aborts) | D |
| `WorktreeRemove` | a hook-created worktree is removed | none | no | D |
| `PreCompact` | before context compaction | trigger | yes | O |
| `PostCompact` | after compaction | trigger | no | O |
| `PreModelSwitch` | before a requested model switch | none | yes | O |
| `PostModelSwitch` | after the model changes | none | no | O |
| `Elicitation` | an MCP server asks for user input | server name | yes (documented) | D |
| `ElicitationResult` | after the user answers one | server name | yes (documented) | D |
| `SessionEnd` | the session ends | reason | no | O |

`PermissionDenied`, `Notification`, `StopFailure`, `TeammateIdle`, `DirectoryAdded`, `WorktreeCreate`, `WorktreeRemove`, `Elicitation` and `ElicitationResult` are unverified for payload shape because provoking them needs an interactive session, a real API failure, an auto-mode denial, or an MCP server with user input. An attempt to provoke `PermissionDenied` in auto mode produced an allow, not a denial; `/add-dir` in `-p` did not fire `DirectoryAdded`.

## Handler types and what happens when one fails

Five handler types are documented: `command` (shell form, or exec form with `args` and no shell), `http` (POST the JSON, read JSON back), `mcp_tool` (call a tool on a configured MCP server), `prompt` (ask a model, one turn) and `agent` (a subagent with tools). Timeouts default to 600 s for command, http and mcp_tool, 30 s for prompt, 60 s for agent, 30 s on `UserPromptSubmit` and the model-switch events, 10 s on `MessageDisplay`, and `SessionEnd` shares a 1.5 s budget ([hooks reference](https://code.claude.com/docs/en/hooks.md)).

The question that matters to a guard: **if the hook itself fails, does the tool call run?** Observed on a `PreToolUse` `Bash` hook, with the call either left to the default or with `onFailure: "block"` (`-ob`):

| Failure | Default | `onFailure: "block"` |
|---|---|---|
| command exits 0, no output | runs | runs |
| command exits 2 | **blocked** | blocked |
| command exits 1 | runs | **blocked** |
| command exits 127, missing executable, missing shell | runs | **blocked** |
| command times out | runs | **blocked** |
| command prints JSON that fails to parse (`{"a": }`), exit 0 | runs | **blocked** |
| command prints text that merely starts with `{` (`{bad`), exit 0 | runs | runs (read as plain text) |
| command prints JSON with an invalid field, exit 0 | runs | **blocked** |
| command prints plain text, exit 0 | runs | runs |
| http 200 with an allow body | runs | runs |
| http 500, 404, connection refused, timeout | runs | **blocked** |
| http 200 with a plain-text or malformed body | runs | **blocked** |
| mcp_tool: tool fails, or server missing | runs | **runs** (no blocking) |
| prompt hook times out | runs | not applicable (field not supported) |
| prompt or agent hook answers "deny" | blocked | not applicable |

Things to read off this:

- **Only exit code 2 blocks by default.** Any other crash, timeout or exit code is a pass-through. That is why the engine registers `onFailure: "block"` and runs its hook fail-closed.
- **Some garbled replies still pass, even with `onFailure: "block"`.** Output that does not parse as JSON but is not recognisably JSON either (`{bad`, plain text) is treated as text and the call runs. Only output that parses as JSON-looking and then fails (broken JSON, or a schema violation) counts as a failure. A guard cannot lean on `onFailure` to catch every bad reply; it must exit 2 itself.
- **`mcp_tool`, `prompt` and `agent` hooks cannot fail closed.** `onFailure` is documented for command and http only (since 2.1.295), and the `mcp_tool` rows above ran anyway. Prompt hooks that time out also run. A guard built on those handler types fails open.
- **`continue: false` is not a block.** A hook that returned it let the call run.
- **A hook marked `async: true` that exits 2 does not stop the call.** It ran anyway.
- **Exit code beats JSON.** JSON `deny` with exit 1 still denied; JSON `allow` with exit 2 still blocked.
- **A top-level `decision: "block"` in the JSON blocked a `PreToolUse` call**, though the documented field for that event is `permissionDecision`.

## How a decision resolves

Documented: when several hooks answer for one call, deny beats defer, defer beats ask, ask beats allow ([hooks reference](https://code.claude.com/docs/en/hooks.md)). A hook's `allow` does not override a `deny` permission rule (fixed in 2.1.77); a hook `ask` cannot downgrade a deny rule (2.1.101).

Observed:

- Allow plus an exit-2 hook: blocked. Ask plus allow: not run in `-p`, where an ask has no one to answer it.
- **Parallel hooks each receive the original input.** Two hooks matching the same call ran concurrently, each seeing the unmodified `tool_input`.
- **A rewrite from one hook ran even though another hook judged the original.** One hook returned `updatedInput`, with or without a `permissionDecision`, and the tool ran the rewritten input. The hook that would have blocked the original never saw the rewrite. With two rewrites, one won; which one is not specified. A rewrite plus a deny hook: blocked (deny wins).
- In `-p`, an `ask` behaves as a deny. Under `bypassPermissions` the same `ask` and `deny` JSON also stopped the call, so bypass does not discard a hook's ask or deny.
- Plan mode ran nothing and produced no hook output for the five cases tried (ask, deny, allow, exit 2, silent), because the model had no tool to call.
- `defer` stopped the call in `-p`. The documentation says it is meant for `-p` with a single tool call, then resuming; nothing about it helps an interactive guard.

## Registration surfaces

Documented places hooks come from ([hooks reference](https://code.claude.com/docs/en/hooks.md), [settings](https://code.claude.com/docs/en/settings.md), [plugins](https://code.claude.com/docs/en/plugins-reference.md)): user settings, project settings, local project settings, managed policy settings, plugins (`hooks/hooks.json`), and skill and agent frontmatter. Switches that change what loads: `disableAllHooks`, `allowManagedHooksOnly`, `strictPluginOnlyCustomization`, `--settings`, `--setting-sources`, `--bare`, `--safe-mode`, `--restricted`.

Observed:

| Surface or switch | Result |
|---|---|
| Hook in project settings, in local settings, in `--settings` | each ran |
| Hook in a skill's frontmatter | ran for Bash calls after the skill was invoked in one run, and did not in an earlier run where the model made fewer calls; one sample each, so not conclusive |
| Hook in an agent's frontmatter | did **not** fire for the Bash call the subagent made (one run) |
| `--plugin-dir` hook | ran, and its `updatedInput` rewrite ran too |
| `disableAllHooks: true` in project settings, in local settings, or in `--settings` | **all hooks stopped**, including ones from other files and from `--settings` |
| `disableAllHooks: true` in one scope, `false` in a higher-priority one | the `false` won: a `--settings` `false` re-enabled hooks over project `true`, and local `false` over project `true` |
| Write `disableAllHooks` into local settings **during** a `bypassPermissions` session | later tool calls ran without hooks (live reload). In the one run that spaced the calls with a 6 s sleep, hooks ran for the first two calls and not the third; in runs where the model issued the calls in parallel the result depended on timing, so the delay before it takes effect is not pinned down |
| Same write without `bypassPermissions` | refused by Claude Code itself: writes under `.claude/` need a grant the `-p` session did not have |
| Add a hook to local settings during a session | not established: the added hook was a silent command, and the run's other calls all ran the existing hook. Unverified |
| `--safe-mode` | no hooks ran (the tool call still ran) |
| `--setting-sources local` (excluding project) | project hooks dropped, `--settings` hooks kept |
| `--bare`, and `--bare` with `--plugin-dir` | not established: the session reported "Not logged in" (it needs an API key), so no tool call happened. Unverified |
| Project hook rewriting input, `--settings` hook logging | the rewrite ran |

Two consequences for damage control:

1. **`disableAllHooks` is a one-line off switch writable from project or local settings.** `~/.claude/settings.json` is already in the engine's protected control plane, but project and local settings are ordinary files the engine does not protect. Outside `bypassPermissions`, Claude Code's own protected-path prompt stands in the way (observed as a refusal in `-p`); under bypass nothing does. The [settings-change guard](config-change.md) blocks a `disableAllHooks` write when Claude Code reports the change, and its [first layer](config-change.md#the-first-layer-the-tool-call-that-writes-the-file) refuses the tool call that makes it. `ConfigChange` is the second layer, not the first: whether Claude Code fires `ConfigChange` for every edit path is something that guard's own document tracks.
2. **A nested `claude` invocation can drop the guard without touching a file.** `--safe-mode`, `--setting-sources` (dropping the project scope) and `--settings '{"disableAllHooks": true}'` changed which hooks ran (observed). `--plugin-dir` added a hook (observed). `--bare` and `CLAUDE_CONFIG_DIR` are documented to change it; both lost authentication here, so they are unverified. The engine now judges these command lines by what they do ([nested `claude` runs](threat-model.md#nested-claude-runs)): `--bare`, `--safe-mode`, `--settings` carrying `disableAllHooks` and a `--setting-sources` list without the user scope block; `--plugin-dir`, `--settings <file>`, `CLAUDE_CONFIG_DIR` and a partial source list ask.

Not exercised: managed settings and `allowManagedHooksOnly`, `--restricted`, `strictPluginOnlyCustomization`, `--bare`. Unverified.

## Conditions: `matcher` and `if`

**`matcher`** is documented as an exact name, a `|` list, or an unanchored JavaScript regular expression over the event's filter field (the tool name for tool events). `FileChanged` takes literal filenames; `StopFailure`, `Notification` and others filter on their own field (see the table above). MCP tools are named `mcp__<server>__<tool>`; the engine registers `mcp__.*`. Observed: a regex over `source` filtered `ConfigChange` as documented ([config-change](config-change.md#what-was-observed)).

**`if`** is a permission-rule string (`Bash(git *)`, `Edit(*.ts)`) that lets Claude Code skip spawning the hook. It is evaluated only on tool events; on any other event a hook with `if` never runs. Added in 2.1.85 and fixed repeatedly since: compound commands (2.1.89), `$()` and backticks (2.1.163, 2.1.243), path rules (2.1.176), the `dir/**` single-segment form (2.1.214), Monitor commands (2.1.314). That fix history is the argument against it: a guard with a pre-filter has the filter's bugs on top of its own. Verdict in [Verdicts](#verdicts): do not use `if` on a security hook.

**Monitor.** Since 2.1.314 a hook matching `Bash` also runs on commands the `Monitor` tool starts; such hooks can block or ask but not approve or rewrite them. Observed: a `Bash` matcher fired for a Monitor call's command. **If both `Bash` and `Monitor` matchers are registered, the command is judged twice.** The engine registers `Monitor` explicitly (issue #49), so on 2.1.314 and later it is judged twice, which is harmless but doubles audit rows.

## Version history

Dates by Claude Code version, from the official changelog. Selected entries; the full list read is every hook-related line from 1.0.x to 2.1.318.

| Version | Change |
|---|---|
| 1.0.48 | `PreCompact` |
| 1.0.54 | `UserPromptSubmit`; working directory in payloads |
| 1.0.59 | `permissionDecision` exposed, including `ask` |
| 1.0.62 | `SessionStart` |
| 1.0.68 | `disableAllHooks` |
| 1.0.85 | `SessionEnd` |
| 2.0.30 | prompt-based stop hooks |
| 2.0.43 | `SubagentStart`; `tool_use_id` in payloads |
| 2.0.45 | `PermissionRequest` |
| 2.1.0 | hooks in agent frontmatter; prompt and agent hooks from plugins |
| 2.1.9 | `additionalContext` from `PreToolUse` |
| 2.1.10 | `Setup` |
| 2.1.33 | `TeammateIdle`, `TaskCompleted` |
| 2.1.49 | `ConfigChange`; `disableAllHooks` respects the managed hierarchy |
| 2.1.50 | `WorktreeCreate`, `WorktreeRemove` |
| 2.1.63 | HTTP hooks |
| 2.1.69 | `InstructionsLoaded`; `agent_id` and `agent_type` in payloads |
| 2.1.76 | `PostCompact`, `Elicitation`, `ElicitationResult` |
| 2.1.77 | a hook's allow no longer bypasses deny rules |
| 2.1.78 | `StopFailure` |
| 2.1.83 | `CwdChanged`, `FileChanged` |
| 2.1.84 | `TaskCreated` |
| 2.1.85 | `if` field |
| 2.1.89 | `defer`; `PermissionDenied` |
| 2.1.101 | deny rules override a hook's ask |
| 2.1.118 | `mcp_tool` handler |
| 2.1.121 | `updatedToolOutput` for every tool |
| 2.1.139 | exec-form `args`; `continueOnBlock` |
| 2.1.141 | `terminalSequence` output |
| 2.1.152 | `MessageDisplay` |
| 2.1.219 | `DirectoryAdded` |
| 2.1.251 | `PreModelSwitch`, `PostModelSwitch` |
| 2.1.295 | `onFailure: "block"` for command and http |
| 2.1.300 | `updatedInput` validated like Claude's own input |
| 2.1.314 | Bash hooks run for Monitor commands |
| 2.1.317 | `onFailure: "block"` for SDK callbacks |

`UserPromptExpansion` and `PostToolBatch` have no dated changelog entry in the lines read; their introduction versions are unverified.

## Observation results

Where the observations differ from the documentation or from what this repo already says:

- **`agent_id` is observed.** [Coverage](coverage.md) says the `agent_id` on a subagent's tool call is from the binary's schema and not observed live. It is now: a `Bash` and a `Glob` call made inside a subagent carried `agent_id` and `agent_type` (Appendix A). Nothing in the coverage claim needs to change except that sentence.
- **The tool is called `Agent` in the payload**, with the subagent request in `tool_input`. Coverage lists `Agent (alias Task)`; the payload name observed was `Agent`.
- **A `Skill` tool call is a normal tool event** with the skill name in `tool_input`, and `PostToolUse` carried `success` and `commandName`.
- **`@file` mentions do not pass through `PreToolUse`.** A prompt that said "state what `@secret.env` contains" delivered the file's text to the model without any tool call, so no `Read` hook saw it. `UserPromptSubmit` did fire, with the raw prompt. The documented environment variable `CLAUDE_CODE_DISABLE_FILE_MENTIONS` turns the behaviour off; the setting is not observed. The engine's path rules therefore do not cover a file the user (or a pasted prompt) mentions with `@`.
- **A rewrite from a second hook is not seen by the first.** See [How a decision resolves](#how-a-decision-resolves).
- **`PreToolUse` carries `permission_mode`, `tool_use_id`, `transcript_path`, `prompt_id`, `cwd` and an `effort` object**; inside a subagent also `agent_id` and `agent_type`. `PostToolUse` adds `tool_response` and `duration_ms`. Appendix A has each, per tool.
- **`Monitor` payload:** `command`, `description` and `timeout_ms`; no `url` case was exercised.
- **MCP payload:** `PreToolUse` for `mcp__scratch__echo` carried the arguments and an `mcp_server` object with the server name and its source; `PostToolUse` carried the server's result.
- **Hook environment.** The logging hook saw `CLAUDE_PROJECT_DIR`; `CLAUDE_EFFORT` on tool events; `CLAUDE_ENV_FILE` on `SessionStart`; and, for `ConfigChange`, the `env` block of the settings file ([config-change](config-change.md#what-was-observed)). Hooks run with the session's cwd.
- **`PreCompact` and `PostCompact`** fired for a manual compaction (`trigger: manual`), followed by `SessionStart` with source `compact`.
- **`InstructionsLoaded`** fired for the project `CLAUDE.md` (`session_start`) and for a nested `CLAUDE.md` when a file in that directory was read (`nested_traversal`).

## Verdicts

**Use now** means an issue in the proposed batch would add it. **Use later** means useful but with a dependency or a cost not worth paying yet. **Not applicable** means it cannot serve a guard, or is out of scope. Each verdict is a paraphrase of the cited documentation plus the observation above.

### Events

| Event | Verdict | Why |
|---|---|---|
| `PreToolUse` | in use | the gate. Everything the engine judges comes through it |
| `ConfigChange` | in use (#50) | sees settings changes however they were made; see [config-change](config-change.md) |
| `PermissionRequest` | use later | fires only when a decision is needed, so it never sees calls the user's allow rules already approved; cannot replace `PreToolUse`. A deny-only second opinion is possible, but the gain over `PreToolUse` is small |
| `PostToolUse` | use later | cannot block; useful for auditing a rewritten input (the gap in [How a decision resolves](#how-a-decision-resolves)) and for noticing a write to a protected file after the fact |
| `UserPromptSubmit` | use later | the only hook that sees an `@file` mention (observed). It can add context or block the prompt (documented, effect not observed). Worth a spike once the path rules can be reused for text |
| `UserPromptExpansion` | not applicable | fires for commands and skills the user typed; the user is the author; observed payload carries only the command name and arguments |
| `PostToolUseFailure`, `PostToolBatch`, `MessageDisplay` | not applicable | feedback or display only |
| `SessionStart`, `SessionEnd`, `Setup` | not applicable | cannot block; `SessionStart` could warn if the guard is missing, but `status` and `doctor` already do that from outside |
| `InstructionsLoaded` | not applicable | cannot block; a loaded `CLAUDE.md` is data the model reads, not an action |
| `SubagentStart` | not applicable | cannot block (documented); the subagent's own tool calls reach `PreToolUse` with `agent_id` (observed) |
| `SubagentStop`, `Stop` | not applicable | can only extend a turn |
| `TaskCreated`, `TaskCompleted`, `TeammateIdle` | not applicable | bookkeeping |
| `PreCompact`, `PostCompact` | not applicable | compaction is not an attack surface the rules model |
| `PreModelSwitch`, `PostModelSwitch` | not applicable | a model change does not touch files |
| `CwdChanged`, `FileChanged` | not applicable | `FileChanged` watches names the hook lists; the engine already protects those paths at write time |
| `Notification`, `StopFailure`, `PermissionDenied` | not applicable | cannot block; unobserved |
| `DirectoryAdded` | use later | widening the working directory widens what Claude Code treats as in-project; cannot block (documented), but a post-hoc audit row is cheap. Unobserved |
| `WorktreeCreate`, `WorktreeRemove` | not applicable | replace git behaviour; a guard has no business there. Unobserved |
| `Elicitation`, `ElicitationResult` | not applicable | an MCP server asking the user a question; unobserved |

Earlier low-value verdicts, re-checked against the observations: all hold except `UserPromptSubmit`, which moves from "not applicable" to "use later" because of the `@file` finding.

### Capabilities

| Capability | Verdict | Why |
|---|---|---|
| exit code 2 | in use | the only block that is unconditional on every handler type that supports it |
| JSON `ask` | in use | the engine's ask rung |
| `onFailure: "block"` (command) | in use | makes a crashed or timed-out guard fail closed; does not catch every garbled reply |
| `onFailure: "block"` (http) | use later | would let a remote judge fail closed, but adds a network dependency to every call |
| `if` | not applicable | a pre-filter inherits the filter's bugs (fix history above); a guard should see every call and decide itself |
| `matcher` | in use | the registered tool names (see [coverage](coverage.md)) |
| `updatedInput` | not applicable as a guard tool, **use now as a threat to cover** | a second hook's rewrite is not judged (observed). Proposed: judge or audit rewrites |
| `updatedToolOutput` | not applicable | post-hoc; cannot gate a call. Unobserved |
| `additionalContext` | not applicable | text for the model, not a decision. Unobserved effect |
| `defer` | not applicable | `-p` only, single tool call (documented, and observed to stop the call) |
| `continue: false`, `systemMessage`, `terminalSequence` | not applicable | `continue: false` is not a block (observed) |
| `async` | not applicable | an async hook's exit 2 does not block (observed) |
| `http` handler | use later | see `onFailure: "block"` (http) |
| `mcp_tool`, `prompt`, `agent` handlers | not applicable | cannot fail closed (observed for mcp_tool and prompt timeout); a model-judged gate is non-deterministic |
| exec-form `args` | in use | the installer's registration form; no shell, no quoting |
| hooks in skill or agent frontmatter | not applicable | opt-in from the author of the skill, not enforceable by the user |
| plugin hooks | not applicable | a plugin can add hooks (observed, including a rewrite), but the guard registers in settings |

## Proposed next batch

Ordered by how much risk each closes per unit of work. Titles only; none is filed.

1. ~~**Judge nested `claude` invocations that disable hooks.**~~ Done: [nested `claude` runs](threat-model.md#nested-claude-runs).
2. **Judge writes to `disableAllHooks` and to the `hooks` key in project and local settings, at the tool call.** [`ConfigChange`](config-change.md) catches the change when Claude Code reports it; Done: `PreToolUse` now refuses the tool call that makes it ([the first layer](config-change.md#the-first-layer-the-tool-call-that-writes-the-file)). Observed: a write to the local settings file under `bypassPermissions` silenced later calls in a live session.
3. **Defend against `updatedInput` from another hook.** Decide among: ask or block when any hook in the session rewrites input, audit rewrites with `PostToolUse`, or document that the guard cannot see them. Needs a spike on whether `PostToolUse` can see both inputs.
4. **Spike `UserPromptSubmit` for `@` mentions.** Run the existing read rules over `@path` tokens in the prompt, and decide what a block does to a user-typed prompt. Pair with a note on `CLAUDE_CODE_DISABLE_FILE_MENTIONS`.
5. **Stop double-judging `Monitor` on 2.1.314 and later.** Registering `Bash` and `Monitor` both runs the command check twice. Decide between deduping in the audit log and registering `Monitor` only below the version that routes it through `Bash` (2.1.314).
6. **Reconcile the coverage page's `agent_id` sentence and the `Agent` tool name** with what was observed (docs-only; may fold into item 1's PR).
7. **Observe the unverified events from an interactive session.** `PermissionDenied`, `Notification`, `StopFailure`, `DirectoryAdded`, `TeammateIdle`, `WorktreeCreate`/`WorktreeRemove`, `Elicitation`/`ElicitationResult`, resume and fork `SessionStart`, managed settings and `allowManagedHooksOnly`, `--restricted`, and an interactive `ask` under bypass. Needs a person at the terminal, so not automatable by a worker.

## Unverified

Not observed in this work, and so not used to back any verdict above:

- Payload shape of `Notification`, `StopFailure`, `PermissionDenied`, `DirectoryAdded`, `TeammateIdle`, `WorktreeCreate`, `WorktreeRemove`, `Elicitation`, `ElicitationResult`.
- `SessionStart` with source `resume` or `fork`.
- `ConfigChange` with source `user_settings` or `policy_settings` (needs a real user or managed file).
- Managed settings, `allowManagedHooksOnly`, `strictPluginOnlyCustomization`, `--restricted`.
- `--bare` with working authentication (it needs an API key), so only "no hooks fired" is known.
- Effects of `updatedToolOutput`, and of `additionalContext` or a block from `PostToolUse`, `UserPromptSubmit`, `UserPromptExpansion`.
- An interactive `ask`, and what `bypassPermissions` does to it, in an attended session.
- The version that introduced `PostToolBatch` and `UserPromptExpansion`.
- Anything on a Claude Code version other than 2.1.319.
- Windows and PowerShell hook behaviour (the changelog records several fixes; not tried).

## Reproducing the observations

The harness lives outside the repo (it is throwaway), but the core is small and can be rebuilt:

```python
#!/usr/bin/env python3
# log_hook.py <log> <label>: append stdin's JSON payload to <log> as one JSONL row,
# then do whatever ctl[label] says (sleep, print, exit code).
import json, os, sys, time
log, label = sys.argv[1], sys.argv[2]
raw = sys.stdin.read()
payload = json.loads(raw)
row = {"t": time.time(), "label": label, "pid": os.getpid(), "cwd": os.getcwd(),
       "stdin_tty": sys.stdin.isatty(), "payload": payload}
with open(log, "a") as fh:
    fh.write(json.dumps(row) + "\n")
```

Register it for every event in a scratch `--settings` file, run `claude -p --setting-sources project,local --no-session-persistence --settings <file> --debug-file <file> "<prompt>"` in a scratch directory, and read the JSONL. Handler-failure cases swap the hook's command for one that exits with a chosen code, sleeps, or prints chosen text, and compare whether the tool's side effect (a `touch` of a sentinel file) happened.

## Sources

Fetched 2026-11; the version each page described was 2.1.318 or newer.

- [Hooks reference](https://code.claude.com/docs/en/hooks.md) — events, payloads, decisions, handler fields, `matcher`, `if`
- [Hooks guide](https://code.claude.com/docs/en/hooks-guide.md) — worked examples and the handler types
- [Settings](https://code.claude.com/docs/en/settings.md), [settings reference](https://code.claude.com/docs/en/settings-reference.md) — hook locations, `disableAllHooks`, `allowManagedHooksOnly`
- [Managed settings](https://code.claude.com/docs/en/managed-settings.md), [server-managed settings](https://code.claude.com/docs/en/server-managed-settings.md)
- [Plugins reference](https://code.claude.com/docs/en/plugins-reference.md), [plugin components](https://code.claude.com/docs/en/plugins-components.md) — plugin hooks
- [Skills](https://code.claude.com/docs/en/skills.md), [subagents](https://code.claude.com/docs/en/sub-agents.md) — frontmatter hooks
- [Permissions](https://code.claude.com/docs/en/permissions.md), [permission modes](https://code.claude.com/docs/en/permission-modes.md) — rule syntax for `if`, mode behaviour
- [CLI reference](https://code.claude.com/docs/en/cli-reference.md), [environment variables](https://code.claude.com/docs/en/env-vars.md), [headless](https://code.claude.com/docs/en/headless.md)
- [MCP](https://code.claude.com/docs/en/mcp.md), [tools reference](https://code.claude.com/docs/en/tools-reference.md), [agent teams](https://code.claude.com/docs/en/agent-teams.md), [worktrees](https://code.claude.com/docs/en/worktrees.md), [sandboxing](https://code.claude.com/docs/en/sandboxing.md)
- [Changelog](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md) — version history

In this repo: [coverage](coverage.md), [settings-change guard](config-change.md), [threat model](threat-model.md), [extending](extending.md).

## Appendix A: observed payloads

Captured from Claude Code 2.1.319 by the logging hook above. Paths are shortened: the scratch directory is `/scratch`, the home directory `/home/user`, ids are replaced with placeholders. Long text fields are cut at 200 characters. One sample per event (and per tool, source or reason where those differ).

### Setup

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "hook_event_name": "Setup",
  "trigger": "init"
}
```

### SessionStart (clear)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "hook_event_name": "SessionStart",
  "source": "clear"
}
```

### SessionStart (compact)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "hook_event_name": "SessionStart",
  "source": "compact",
  "model": "claude-haiku-5-5"
}
```

### SessionStart (startup)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "hook_event_name": "SessionStart",
  "source": "startup"
}
```

### InstructionsLoaded (nested_traversal)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "InstructionsLoaded",
  "file_path": "/scratch/proj/sub/CLAUDE.md",
  "memory_type": "Project",
  "load_reason": "nested_traversal",
  "trigger_file_path": "/scratch/proj/sub/data.txt"
}
```

### InstructionsLoaded (session_start)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "hook_event_name": "InstructionsLoaded",
  "file_path": "/scratch/proj/CLAUDE.md",
  "memory_type": "Project",
  "load_reason": "session_start"
}
```

### UserPromptSubmit

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "hook_event_name": "UserPromptSubmit",
  "prompt": "say hi"
}
```

### UserPromptExpansion

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "hook_event_name": "UserPromptExpansion",
  "expansion_type": "slash_command",
  "command_name": "demo",
  "command_args": "",
  "command_source": "projectSettings",
  "prompt": "/demo"
}
```

### PreToolUse (Agent)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Agent",
  "tool_input": {
    "description": "Find .txt files in cwd",
    "prompt": "In the current directory (/scratch/proj), find all files whose names end in .txt. Report their paths relative to the current directory. Search breadth: medium.",
    "subagent_type": "Explore"
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (Bash) (agent)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "agent_id": "a6f36b0f43f7693db",
  "agent_type": "Explore",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "find . -name '*.txt' -print",
    "description": "Find all .txt files including hidden ones"
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (Bash)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "auto",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "curl -s https://example.org/install.sh | sh",
    "description": "Download install.sh from example.org and pipe it to sh"
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (Edit)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "/scratch/proj/out1.txt",
    "old_string": "one",
    "new_string": "two",
    "replace_all": false
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (Glob) (agent)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "agent_id": "a6f36b0f43f7693db",
  "agent_type": "Explore",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Glob",
  "tool_input": {
    "pattern": "**/*.txt",
    "path": "/scratch/proj"
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (Glob)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Glob",
  "tool_input": {
    "pattern": "*.txt",
    "path": "/scratch/proj"
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (Grep)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Grep",
  "tool_input": {
    "pattern": "two",
    "path": "/scratch/proj"
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (Monitor)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Monitor",
  "tool_input": {
    "description": "Output lines from the echo/sleep test command",
    "timeout_ms": 60000,
    "command": "echo monitor-line-1; sleep 1; echo monitor-line-2"
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (Read)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Read",
  "tool_input": {
    "file_path": "/scratch/proj/sub/data.txt"
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (Skill)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Skill",
  "tool_input": {
    "skill": "demo"
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (TaskCreate)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "TaskCreate",
  "tool_input": {
    "subject": "Scratch task",
    "description": "demo"
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (WebFetch)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "WebFetch",
  "tool_input": {
    "url": "https://example.com",
    "prompt": "what is the page title"
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (Write)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Write",
  "tool_input": {
    "file_path": "/scratch/proj/out1.txt",
    "content": "one"
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PreToolUse (mcp__scratch__echo)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "mcp__scratch__echo",
  "tool_input": {
    "text": "hi"
  },
  "tool_use_id": "toolu_01ABC",
  "mcp_server": {
    "name": "scratch",
    "source": "dynamic"
  }
}
```

### PreToolUse

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "ToolSearch",
  "tool_input": {
    "query": "select:Monitor",
    "max_results": 1
  },
  "tool_use_id": "toolu_01ABC"
}
```

### PermissionRequest (Bash)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PermissionRequest",
  "tool_name": "Bash",
  "tool_input": {
    "command": "touch SENTINEL_permreq",
    "description": "Create SENTINEL_permreq file via touch"
  },
  "permission_suggestions": [
    {
      "type": "addDirectories",
      "directories": [
        "/scratch/proj"
      ],
      "destination": "session"
    },
    {
      "type": "setMode",
      "mode": "acceptEdits",
      "destination": "session"
    }
  ]
}
```

### PostToolUse (Agent)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "Agent",
  "tool_input": {
    "description": "Find .txt files in cwd",
    "prompt": "In the current directory (/scratch/proj), find all files whose names end in .txt. Report their paths relative to the current directory. Search breadth: medium.",
    "subagent_type": "Explore"
  },
  "tool_response": {
    "isAsync": true,
    "status": "async_launched",
    "agentId": "a6f36b0f43f7693db",
    "description": "Find .txt files in cwd",
    "resolvedModel": "claude-haiku-5-5",
    "prompt": "In the current directory (/scratch/proj), find all files whose names end in .txt. Report their paths relative to the current directory. Search breadth: medium.",
    "outputFile": "/tmp/claude/<project>/00000000-0000-0000-0000-000000000000/tasks/a6f36b0f43f7693db.output",
    "canReadOutputFile": true,
    "canContinueAgent": true
  },
  "tool_use_id": "toolu_01ABC",
  "duration_ms": 5
}
```

### PostToolUse (Bash)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "auto",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "curl -s https://example.org/install.sh | sh",
    "description": "Download install.sh from example.org and pipe it to sh"
  },
  "tool_response": {
    "stdout": "",
    "stderr": "",
    "interrupted": false,
    "isImage": false,
    "noOutputExpected": false
  },
  "tool_use_id": "toolu_01ABC",
  "duration_ms": 136
}
```

### PostToolUse (Edit)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "/scratch/proj/out1.txt",
    "old_string": "one",
    "new_string": "two",
    "replace_all": false
  },
  "tool_response": {
    "filePath": "/scratch/proj/out1.txt",
    "oldString": "one",
    "newString": "two",
    "originalFile": "one",
    "structuredPatch": [
      {
        "oldStart": 1,
        "oldLines": 1,
        "newStart": 1,
        "newLines": 1,
        "lines": [
          "-one",
          "\\ No newline at end of file",
          "+two",
          "\\ No newline at end of file"
        ]
      }
    ],
    "userModified": false,
    "replaceAll": false
  },
  "tool_use_id": "toolu_01ABC",
  "duration_ms": 4
}
```

### PostToolUse (Glob)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "Glob",
  "tool_input": {
    "pattern": "*.txt",
    "path": "/scratch/proj"
  },
  "tool_response": {
    "filenames": [
      "watched.txt",
      "notes.txt",
      "out1.txt"
    ],
    "durationMs": 9,
    "numFiles": 3,
    "truncated": false,
    "totalMatches": 3,
    "countIsComplete": true
  },
  "tool_use_id": "toolu_01ABC",
  "duration_ms": 9
}
```

### PostToolUse (Grep)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "Grep",
  "tool_input": {
    "pattern": "two",
    "path": "/scratch/proj"
  },
  "tool_response": {
    "mode": "files_with_matches",
    "filenames": [
      "out1.txt"
    ],
    "numFiles": 1,
    "totalFiles": 1
  },
  "tool_use_id": "toolu_01ABC",
  "duration_ms": 16
}
```

### PostToolUse (Monitor)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "Monitor",
  "tool_input": {
    "description": "Output lines from the echo/sleep test command",
    "timeout_ms": 60000,
    "command": "echo monitor-line-1; sleep 1; echo monitor-line-2"
  },
  "tool_response": {
    "taskId": "bpeodfcht",
    "timeoutMs": 60000,
    "persistent": false
  },
  "tool_use_id": "toolu_01ABC",
  "duration_ms": 143
}
```

### PostToolUse (Read)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "Read",
  "tool_input": {
    "file_path": "/scratch/proj/sub/data.txt"
  },
  "tool_response": {
    "type": "text",
    "file": {
      "filePath": "/scratch/proj/sub/data.txt",
      "content": "data\n",
      "numLines": 2,
      "startLine": 1,
      "totalLines": 2
    }
  },
  "tool_use_id": "toolu_01ABC",
  "duration_ms": 2
}
```

### PostToolUse (Skill)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "Skill",
  "tool_input": {
    "skill": "demo"
  },
  "tool_response": {
    "success": true,
    "commandName": "demo"
  },
  "tool_use_id": "toolu_01ABC",
  "duration_ms": 3
}
```

### PostToolUse (TaskCreate)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "TaskCreate",
  "tool_input": {
    "subject": "Scratch task",
    "description": "demo"
  },
  "tool_response": {
    "task": {
      "id": "1",
      "subject": "Scratch task",
      "description": "demo"
    }
  },
  "tool_use_id": "toolu_01ABC",
  "duration_ms": 24
}
```

### PostToolUse (Write)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "Write",
  "tool_input": {
    "file_path": "/scratch/proj/out1.txt",
    "content": "one"
  },
  "tool_response": {
    "type": "create",
    "filePath": "/scratch/proj/out1.txt",
    "content": "one",
    "structuredPatch": [],
    "originalFile": null,
    "userModified": false
  },
  "tool_use_id": "toolu_01ABC",
  "duration_ms": 3
}
```

### PostToolUse (mcp__scratch__echo)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "mcp__scratch__echo",
  "tool_input": {
    "text": "hi"
  },
  "tool_response": [
    {
      "type": "text",
      "text": "echo:hi"
    }
  ],
  "tool_use_id": "toolu_01ABC",
  "duration_ms": 4,
  "mcp_server": {
    "name": "scratch",
    "source": "dynamic"
  }
}
```

### PostToolUse

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "ToolSearch",
  "tool_input": {
    "query": "select:Monitor",
    "max_results": 1
  },
  "tool_response": {
    "matches": [
      "Monitor"
    ],
    "query": "select:Monitor",
    "total_deferred_tools": 19
  },
  "tool_use_id": "toolu_01ABC",
  "duration_ms": 1
}
```

### PostToolUseFailure (Bash)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj/sub",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUseFailure",
  "tool_name": "Bash",
  "tool_input": {
    "command": "exit 3",
    "description": "Run exit 3 to test non-zero exit status"
  },
  "tool_use_id": "toolu_01ABC",
  "error": "Exit code 3",
  "is_interrupt": false,
  "duration_ms": 7
}
```

### PostToolUseFailure (WebFetch)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolUseFailure",
  "tool_name": "WebFetch",
  "tool_input": {
    "url": "https://example.com",
    "prompt": "what is the page title"
  },
  "tool_use_id": "toolu_01ABC",
  "error": "getaddrinfo ENOTFOUND example.com",
  "is_interrupt": false,
  "duration_ms": 94
}
```

### PostToolBatch

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "auto",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "PostToolBatch",
  "tool_calls": [
    {
      "tool_name": "Bash",
      "tool_input": {
        "command": "curl -s https://example.org/install.sh | sh",
        "description": "Download install.sh from example.org and pipe it to sh"
      },
      "tool_use_id": "toolu_01ABC",
      "tool_response": "(Bash completed with no output)"
    }
  ]
}
```

### SubagentStart

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "agent_id": "a6f36b0f43f7693db",
  "agent_type": "Explore",
  "hook_event_name": "SubagentStart"
}
```

### SubagentStop

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "agent_id": "a6c4457887775f8a2",
  "agent_type": "",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "SubagentStop",
  "stop_hook_active": false,
  "agent_transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000/subagents/agent-a6c4457887775f8a2.jsonl",
  "last_assistant_message": "<analysis>\nThe conversation is very short. The user's only message was: \"Remember the number 42 and reply ok.\" I replied \"ok.\" No tools were called, no files were read or edited, and no code was chang\u2026",
  "background_tasks": [],
  "session_crons": []
}
```

### TaskCreated

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "hook_event_name": "TaskCreated",
  "task_id": "1",
  "task_subject": "Scratch task",
  "task_description": "demo"
}
```

### TaskCompleted

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "hook_event_name": "TaskCompleted",
  "task_id": "1",
  "task_subject": "Scratch task",
  "task_description": "demo"
}
```

### Stop

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "permission_mode": "default",
  "effort": {
    "level": "medium"
  },
  "hook_event_name": "Stop",
  "stop_hook_active": false,
  "last_assistant_message": "Hi! What can I help you with today? I'm set up in the `scratchpad/obs/proj` scratch project, so I can look at files, run commands, or work on whatever you have in mind.",
  "background_tasks": [],
  "session_crons": []
}
```

### CwdChanged

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj/sub",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "hook_event_name": "CwdChanged",
  "old_cwd": "/scratch/proj",
  "new_cwd": "/scratch/proj/sub"
}
```

### FileChanged

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj/sub",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "hook_event_name": "FileChanged",
  "file_path": "/scratch/proj/sub/watched.txt",
  "event": "add"
}
```

### PreCompact

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "hook_event_name": "PreCompact",
  "trigger": "manual",
  "custom_instructions": null
}
```

### PostCompact

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "hook_event_name": "PostCompact",
  "trigger": "manual",
  "compact_summary": "<analysis>\nThe conversation is very short. The user's only message was: \"Remember the number 42 and reply ok.\" I replied \"ok.\" No tools were called, no files were read or edited, and no code was chang\u2026"
}
```

### PreModelSwitch (command)

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "hook_event_name": "PreModelSwitch",
  "from_model": "claude-haiku-5-5",
  "to_model": "claude-sonnet-5-5",
  "requested_model": "sonnet",
  "source": "command",
  "context_tokens": 16677,
  "prompt_cache_warm": true,
  "cache_ttl": "1h",
  "estimated_cache_write_usd": 0.0667,
  "pricing": "catalog"
}
```

### PostModelSwitch

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "hook_event_name": "PostModelSwitch",
  "from_model": "claude-haiku-5-5",
  "to_model": "claude-sonnet-5-5",
  "requested_model": "sonnet",
  "source": "command",
  "context_tokens": 16677,
  "prompt_cache_warm": true,
  "cache_ttl": "1h",
  "estimated_cache_write_usd": 0.0667,
  "pricing": "catalog"
}
```

### MessageDisplay

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "hook_event_name": "MessageDisplay",
  "turn_id": "00000000-0000-0000-0000-000000000000",
  "message_id": "00000000-0000-0000-0000-000000000000",
  "index": 0,
  "final": true,
  "delta": "Hi! What can I help you with today? I'm set up in the `scratchpad/obs/proj` scratch project, so I can look at files, run commands, or work on whatever you have in mind."
}
```

### SessionEnd

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "transcript_path": "/home/user/.claude/projects/<project>/00000000-0000-0000-0000-000000000000.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "00000000-0000-0000-0000-000000000000",
  "hook_event_name": "SessionEnd",
  "reason": "other"
}
```

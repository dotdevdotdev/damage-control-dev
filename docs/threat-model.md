# Threat model

damage-control-dev is a **seatbelt, not a sandbox**. It catches an AI coding agent that is about to do something destructive by mistake. It does not contain an agent, and it is not a boundary against anyone who is trying to get around it.

This page says what it is built to catch, what it does not catch, and where it fails open. Read it before you rely on it.

- [What it is built to catch](#what-it-is-built-to-catch)
- [What it does not protect against](#what-it-does-not-protect-against)
- [How a decision is made](#how-a-decision-is-made)
- [Fail-closed and fail-open](#fail-closed-and-fail-open)
- [The scan budget](#the-scan-budget)
- [The control plane and the kill switch](#the-control-plane-and-the-kill-switch)
- [How shell commands are read](#how-shell-commands-are-read)
- [Script indirection](#script-indirection)
- [Defense in depth](#defense-in-depth)
- [Reporting a bypass](#reporting-a-bypass)

## What it is built to catch

The target is the **accidental** catastrophic call from an agent that is trying to help:

- Destructive file and process operations: `rm -rf`, `chmod 777`, `kill -9`, `dd` to a device.
- Destructive git: `git reset --hard`, `git push --force`, `git clean -fd`, `git stash clear`.
- Destructive SQL and database CLIs: `DROP TABLE`, `TRUNCATE`, `DELETE` with no `WHERE`, `FLUSHALL`.
- Reads and writes of secrets: `.env` files, SSH and cloud credentials, private keys, Terraform state.
- Edits to the guard's own configuration: the hook registration in `~/.claude/settings.json`, the policy file, rule overlays.
- Risky MCP tool calls: path arguments that point at protected files, and the policies in the `mcp-tools` group.
- Opt-in vendor packs for AWS, GCP, Firebase, container tooling, infrastructure-as-code and package publishing (`damage-control-dev packs list`).

It also helps when several agent sessions run in parallel and make the same mistake at once, because every session reads the same rules.

The rules are tiered: some operations are **blocked**, some **ask** a human first. [Coverage](coverage.md) lists which tools are judged and how; [rule authoring](rule-authoring.md) explains the tiers.

## What it does not protect against

- **A determined adversary.** A process running as your OS user can edit anything this tool can, including the Python environment the hook runs from. Same-user trust is assumed throughout.
- **Commands you type yourself.** Claude Code runs a command you enter with a leading `!` without a `PreToolUse` event, so nothing here sees it.
- **Tools with no hook event.** Only the tools in [coverage](coverage.md) are judged. `WebFetch`, `WebSearch`, `Task`/`Agent`, `Skill` and others are not.
- **Network egress.** Nothing filters outbound connections or what is sent over them. A command that exfiltrates data with a harmless-looking verb is not stopped.
- **The agent requesting an exception.** An agent that expects a command to be blocked can end it with `# ask: <reason>`. The comment is part of the command text, so the agent writes it, and it grants nothing: a block (a hard block, a read-only, no-delete or zero-access path, a protected command) becomes an `ask`, and the human sees the agent's reason and decides that one command. The ask is not lowered by `bypassPermissions`, `auto` or `acceptEdits`, and in an unattended session it stays a block, whatever `unattended_allow` lists. The control plane ignores the comment. A command that would be allowed is unchanged. The audit row records the reason, the original rule id and that the verdict was raised from `block`. `# allow:` has no effect.
- **What a script does after the hook read it.** Files a command runs, and the recipes `make`, `npm run` and `just` run, are read once, when the hook runs. See [script indirection](#script-indirection) for what is not read.
- **Containment and resource limits.** No filesystem sandbox, no CPU, memory or disk quota, no process isolation. Claude Code's own sandbox is the layer that limits what a started command can reach; it is off by default and covers shell commands only. See [pairing with the sandbox](sandbox.md), and run `damage-control-dev doctor` to see whether it is on and whether its unsandboxed retry is open.
- **Logic errors and bad code.** Code that corrupts data through an application bug looks like any other code.
- **Supply chain attacks.** A malicious dependency is not a destructive command until something runs it.
- **Other harnesses and platforms.** Only Claude Code on macOS and Linux is supported.

Expect false positives (an `ask` you did not need) and false negatives (a destructive command the rules do not know). The working policy is: ask, then learn. Add a rule when you find a gap.

## How a decision is made

Each tool call becomes one of three outcomes:

| Outcome | What the hook does | Exit code |
|---|---|---|
| allow | prints nothing | 0 |
| ask | asks Claude Code to prompt you (a JSON `permissionDecision: "ask"` on stdout) | 0 |
| block | writes the reason to stderr; the tool does not run | 2 |

Exit code 2 is the only code that stops a Claude Code tool call. Exit 1, which is what a crashed Python process produces, means "no decision" and lets the call run. The hook is built around that fact (below).

An `ask` is a question for a human, so what it becomes depends on who is there:

- **Attended, normal mode:** you are prompted.
- **Bypass mode** (Claude Code `permission_mode` of `bypassPermissions` or `auto`): an `ask` is allowed without a prompt. The exception is an *unverifiable* ask (for example `eval "$x"`, where nothing can say what will run). Bypass never demotes those.
- **Unattended** (`DAMAGE_CONTROL_UNATTENDED=1` in the environment of the Claude Code session): there is nobody to answer, so an `ask` becomes a **block**, unless the rule's id is granted in `unattended_allow` (or `DAMAGE_CONTROL_UNATTENDED_ALLOW`). Hard blocks are never granted. An unverifiable ask is blocked unless its own id is granted by name.

Real output from the hook, run against the installed package:

```
$ echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"},"cwd":"/tmp"}' | python -I -m damage_control.hook bash
SECURITY: Blocked: rm with recursive or force flags
Command: rm -rf /
$ echo $?
2

$ echo '{"tool_name":"Bash","tool_input":{"command":"kill -9 5"},"cwd":"/tmp"}' | DAMAGE_CONTROL_UNATTENDED=1 python -I -m damage_control.hook bash
SECURITY: Blocked (unattended — no human to confirm): kill -9 (SIGKILL, no cleanup; use a plain kill first)
Command: kill -9 5
Why: rule 'core.kill-sigkill' is not on the unattended allowlist
```

To see a decision without wiring up a hook, use `damage-control-dev check`. It prints the decision and always exits 0, whatever the decision:

```
$ damage-control-dev check "git push --force origin main"
block: git push --force (use --force-with-lease) [git.git-push-force-use-force-with-lease]
$ damage-control-dev check "kill -9 123"
ask: kill -9 (SIGKILL, no cleanup; use a plain kill first) [core.kill-sigkill]
$ damage-control-dev check ls
allow: No patterns matched
```

`check` judges the command only. It does not apply bypass or unattended mode; those come from the hook's input and environment.

## Fail-closed and fail-open

The design goal is that anything going wrong *inside the hook* ends in a block. Some failures happen outside it, and those fail open.

### Fails closed

| Failure | Result |
|---|---|
| The hook cannot import the engine, or a module exits 0 at import | exit 2 |
| Malformed, non-object or oversized (over 64M characters) stdin | exit 2 |
| Any unhandled exception inside the hook | exit 2 |
| A hook that outlives its own 20 s watchdog | the process exits 2 |
| Command too large or scan out of time | an unverifiable `ask` (see the budget) |
| The policy file does not parse | kill switch stays on, and every group and pack is loaded |
| The interpreter or package is gone | blocked by `onFailure: block` in the registration |

`init` registers each hook with `onFailure: block`, which needs Claude Code 2.1.295 or newer. `init` refuses on older versions unless you pass `--fail-open`, which registers without it and records that choice.

The hook runs as `python -I -m damage_control.hook`. `-I` keeps the working directory and `PYTHON*` variables out of the import path, so a file the agent plants in the project (a `json.py`, say) is not imported as part of the hook.

An audit-log failure (full disk, unwritable log directory) never changes a decision. One line goes to stderr and the computed decision stands.

### Fails open

- **A hook that times out.** Measured on 2026-10-16 with `claude -p`: a `PreToolUse` command hook registered with `timeout: 2` that sleeps 8 s is killed at the timeout and the Bash call **runs anyway**. A hook that exits 2 immediately blocks it. The harness treats a killed hook as "no decision".
  - Mitigation: `init` registers `timeout: 30`, the scan gives up at 10 s, and a 20 s watchdog exits with a block, so the hook decides before the harness can kill it. This holds as long as the machine is not so loaded that the process cannot run at all.
  - `doctor` flags a registered matcher whose timeout is missing or differs from 30. `init` and `doctor --fix` reset it.
- **User-typed `!` commands** and **tools without a hook** (above).
- **Hooks turned off.** `uninstall`, the break-glass script, or removing the entries from `settings.json` all leave damage control off until you run `init` again.
- **Older Claude Code with `--fail-open`.** A crash or missing interpreter lets the call run.
- **The kill switch.** `enabled: false` disables rule enforcement on purpose (see below).

To re-measure the timeout behavior on a new Claude Code version: in an empty directory, register a project-local `PreToolUse` Bash hook with `"timeout": 2` that sleeps 8 s and exits 0, run `claude -p "run exactly this bash command: touch SENTINEL" --permission-mode bypassPermissions --allowedTools Bash`, and see whether `SENTINEL` exists. Repeat with a hook that exits 2 at once as a control; it must block.

## The scan budget

A slow scan is a bypass, because a killed hook allows. So the scan has a budget that fails toward asking:

| Axis | Limit | Result when exceeded |
|---|---|---|
| Command size | 256 K characters | `ask`, id `core.command-too-large` |
| Longest single line | 32 K characters | `ask`, id `core.command-too-large` |
| Scan time | 10 s | `ask`, id `core.scan-budget` |

These asks are *unverifiable*: bypass mode does not demote them and an unattended run blocks them. The limits were set from an audit log of 7.7 k real commands (longest command 28.9 KB, longest line 2.9 KB), which leaves roughly an order of magnitude of headroom. Lines are counted physically, so backslash-continued lines are not joined for the size check; only the clock bounds those.

Read calls are judged on the path only. Edit, Write and NotebookEdit are judged on the path, and their new text is scanned only when it looks like a script of 256 KiB or less ([script indirection](#script-indirection)); anything else, a 50 MB payload included, is never read and costs about 0.1 s.

Running a file adds its own budget, in [script indirection](#script-indirection): file size, nesting depth, files per command and judging time. Those limits end in an unverifiable `ask` too.

If the scan runs out of time and the command mentions a protected path anywhere, only the lines that mention it are re-checked under a short deadline: a positive write is a block, anything unresolved is the unverifiable ask. A bare mention such as `settings.json` is enough to trigger this, which costs an extra ask once the budget is already spent.

## The control plane and the kill switch

Damage control reads its own configuration from files. If the agent it polices could write them, it could switch the guard off, act, and switch it back on. So the **control plane** is protected separately:

- `~/.claude/settings.json` (the hook registration) and `~/.claude/hooks/*`
- the policy file, `~/.damage-control/damagecontrol.yml`
- any `.damagecontrol.yml` in a project
- a host profile manifest, when one is in use (see [extending](extending.md))

Writes, edits, deletes, moves and permission changes on these paths are blocked. The check runs **before** the `# ask: <reason>` comment and **before** the kill switch, so neither can override it. Only the path allowlist (`allowed_paths`, which lives in the same protected files) can re-permit a control-plane path, and an allowlist entry counts only if it names the file or its shape covers it. A location allowance such as `/tmp/*` does not.

The kill switch is `enabled: false` in the policy file or a project `.damagecontrol.yml`. It turns the rules off; it does not turn the control-plane protection off. Verified against the installed package:

```
$ damage-control-dev check "rm -rf /tmp/x"            # with enabled: false in the policy file
allow: safety disabled
$ # the hook, same state, writing to the hook registration:
SECURITY: Blocked: protected control-plane file (host-owned; edit on the host)
exit=2
```

Mind the cost of an overly broad allowlist: because `allowed_paths` outranks control-plane protection, an entry such as `~/.claude/*` with `allow: all` would make the hook registration agent-writable. Keep entries narrow.

## How shell commands are read

Shell is hard to analyze statically. The engine does not execute or parse a full shell; it normalizes the command and runs rules over the result. What it does handle:

- **Quoting and escaping tricks:** `"rm" -rf`, `r\m`, `R=rm; $R -rf x` read as `rm -rf x`.
- **Compound syntax:** a command inside `if`/`while`/`for`/`case`/`{ }`/`( )`/function bodies is judged like the same command at top level.
- **Wrappers and payloads:** `sudo`, `env`, `timeout`, `nohup`, `sh -c "…"`, `ssh host "…"`, `psql -c "…"`, `xargs`, `find -exec`, heredocs and here-strings fed to a shell. The wrapped text is judged as a command in its own right.
- **Hidden-command carriers:** options that run programs, such as `tar --to-command`, `git -c core.sshCommand=…`, `git rebase --exec`, `ssh -o ProxyCommand=…`, `sed` `e`, and `awk` programs that call `system()`.
- **Verbs the shell computes:** `x=ev; $x"al" …` is resolved from definitions in the same command (variables, arrays, aliases, functions, `for` lists) and judged as typed.
- **The separator variable:** `cat${IFS}file`, `cat$IFS$9file` and `cat${IFS:0:1}file` run `cat file`, so they get the verdict of the spaced command, in the verb and operand positions and inside a `-c` or `ssh` payload. The shell's default separator list is assumed. A command that reassigns or unsets `IFS`, or transforms it (`${IFS#?}`), is an unverifiable ask; inside a script that is not asked about.
- **Fetched programs:** a download piped into a shell (`curl … | sh`, `bash <(curl …)`) is blocked with id `core.fetched-program-pipe`. A non-download producer piped into a shell is an unverifiable ask.

What it cannot decide asks rather than guesses: `eval`, base64-to-shell pipelines, a substitution that picks the command, a variable filled at run time. Such an ask carries id `core.ambiguous-command` or `core.indirect-verb`.

### Declared residuals

These are known gaps, stated so you do not discover them by accident:

- **Run-time content.** The text of a list file (`cat list | xargs rm`) is judged by where the list lives, not by what it names. `rm $f` in a loop with non-literal operands is only as strict as the generic `rm` rule.
- **State from another command.** A function, alias or variable defined in an earlier command, `declare -n` namerefs, and `${!x}` indirection are not resolved.
- **Computed consumers after a fetch pipe.** `c=sh; curl u | $c` is not recognized as a shell and is allowed. A fetch pipe inside a substitution (`$(curl u | sh)`) asks instead of blocking.
- **A local interpreter's stdin.** `python3 - <<EOF` and `echo '…' | lua` are checked against protected paths but not against the general verb rules.
- **Programs in files, other than the ones [script indirection](#script-indirection) reads.** `awk -f prog`, `sed -f script` and the like are not read.
- **Check-then-use gaps.** The hook validates a path the command has not used yet.
- **Quoted writer and path.** A writer verb and a protected path both inside one quoted string (`ln`, `curl -o`) is treated as data in a quote.
- **Wrappers with no stable grammar.** `watch`, `script -qc` and similar that carry the command in a quoted string are judged by the payload rescan, not by position.
- **Emptying a file.** Only listed spellings (`truncate`, `dd of=`, `: > f`, `cat /dev/null > f`, …) count as deleting a guarded file; a plain `> f` is an ordinary edit.

If you find one of these closable, or find a gap that is *not* listed here, see [Reporting a bypass](#reporting-a-bypass).

## Script indirection

A command string names a file and the file holds the commands, so judging the string alone lets `bash x.sh` through whatever `x.sh` says. Measured on 0.1.3 through the real hook: a script body containing a recursive forced removal of the root was allowed when run as `bash x.sh`, `sh x.sh`, `cd dir && ./x.sh`, `source x.sh` or `python3 x.py`, and when one command wrote the file and ran it.

From 0.1.4 a command that runs a file is judged on the file's text too, with the same rules as a typed command, and the verdict names the script and the rule: `rm with recursive or force flags [in script /tmp/x.sh; rule core.rm-with-recursive-or-force-flags]`. [Coverage](coverage.md#script-indirection) lists what counts as running a file, and the limits.

How it works:

- **Run-time scan.** The file is resolved (relative paths against the payload cwd and each literal `cd` before it), read through `realpath`, and judged. A block stays a block and an ask stays an ask. A shell script is judged in chunks, each with the assignments and `cd` lines it depends on. For `python`, `node`, `perl` and `ruby` only the arguments of process-spawning and file-deleting calls are read, so a docstring that mentions a command is not a finding.
- **Write then run.** When one command writes a file and runs it, the body it writes is judged, whatever is on disk.
- **Authoring.** `Write`, `Edit` and `NotebookEdit` text that looks like a script (a `#!` line, or a script extension) is judged on write. The finding is an `ask` even where the typed verdict is a block: writing runs nothing, and running the file is judged again. In bypass mode that ask is allowed; unattended, it is blocked.
- **Inside a script, only what the rules positively recognize counts.** A `# ask:` comment in a file is a comment, so a script cannot request an exception for itself. A computed verb or a substitution in a script is not asked about, because every real script has them. The comment on the *command that runs the script* (`bash x.sh # ask: reviewed`) counts, as it does for any command.
- **Fail closed where the file cannot be read:** over 256 KiB, nested more than 3 scripts deep, more than 16 files or 1 MiB in one command, longer than 4 s to judge, unreadable (permission denied, a symlink loop), or named earlier in the same command and not yet there (`curl -o x.sh URL && sh x.sh`). Each is an unverifiable `ask`. A missing file that nothing in the command names first is allowed, because running it fails. A directory, a device, a FIFO and a binary are allowed: there is no script to read. A script that runs itself, directly or through others, is judged once.

Cost: a command that runs no file is judged at the typed speed. Running a file adds time in proportion to its text, because every chunk goes through the full ladder: on an Apple-silicon laptop a hook call takes about 40 ms, a 100-line script brings it to about 70 ms and a dense 9 KB one to about 250 ms. The budget for a command that runs a script is 500 ms. Comments and prose cost less than code. A path under a network or automounted directory adds the filesystem's own lookup time to typed and scripted commands alike.

### Task-runner recipes

`make clean`, `npm test` and `just build` name text that lives in a Makefile, `package.json` or justfile, so judging the command by its name judges an editable label. The recipe is located and judged like a script, under the same size, depth, file and time budgets, and the verdict names the runner, the file and the rule.

- **`make` / `gmake`.** The Makefile in the working directory (or `-C`, or the file named by `-f`; `GNUmakefile`, then `makefile`, then `Makefile`), the named targets and their prerequisites, and one level of `include`. Command-line `NAME=value` operands override the file, as make does. With no target, the default goal is read. A pattern rule is read when the target matches it.
- **`npm`, `pnpm`, `yarn`, `bun`.** `run <script>`, `test`, `start`, and for `yarn` and `pnpm` a bare script name that is not a built-in command: the nearest `package.json` upward from the directory, the `scripts` entry, and its `pre` and `post` hooks.
- **`just`.** The nearest justfile upward (or `-f`, `-d`), the named recipes, their dependencies, positional arguments bound to parameters, `{{name}}` interpolation of literals, and shebang recipes judged in the interpreter's language.
- **Anything unresolved asks.** A variable or function the parser cannot evaluate (`$(shell …)`, a name that comes from the environment), a definition inside a conditional, an `include` of an included file, a computed `-C` or `-f` operand, `make --eval`, a workspace flag (`-w`, `--filter`, `-r`), or a `just` recipe that may live in an imported file is an unverifiable `ask`, id `core.recipe-unverifiable`, which bypass mode does not lower. A finding in the part that was read still wins: a block stays a block. Built-in defaults (`CC`, `CXX`, `RM`, `MAKE`, `AR`) resolve to their usual values, and the automatic variables (`$@`, `$<`, `$^`) resolve per target.
- **A recipe that is not there is allowed**, as for a missing script: a missing target or script name, no Makefile or package.json, a `package.json` that does not parse. Running it fails.
- **The comment on the invoking command works as for scripts.** `make clean # ask: reviewed` turns a block into an ask the human decides; `# allow:` has no effect.
- **Gaps, documented rather than half-parsed.** `task` (Taskfile) needs a YAML parser the standard library does not have. What `make` or `just` evaluate while reading the file (`$(shell …)` in an assignment, backticks in a `just` variable) is not run through the rules. `npm install` lifecycle hooks and `cargo build` scripts are not read. `make -n` is judged as if it ran.

Cost: a typical recipe (a handful of lines) adds less than the noise in a hook call, which takes about 45 to 55 ms end to end on an Apple-silicon laptop; a larger recipe costs what a script of the same size costs, above. The budget for a command that runs a recipe is the same 500 ms.

Expect false positives. The scan applies the typed ladder to scripts, and the ladder blocks `rm -rf build/` typed, so a build script containing it is blocked at run time too. The way through is the same as for a typed command: review the script, then run it with `# ask: <reason>` on the command line and approve the prompt, or put the rule's id in `disabled_rules` in the policy file.

What it does **not** cover:

- **Scripts fetched at run time.** `curl URL | sh` has its own rule. A file downloaded and then run is an `ask` only when the same command names it first.
- **Recipes beyond the runners above.** `task`, `cargo build` scripts, `npm install` lifecycle hooks and `pip install` hooks run text this scan never sees. See [task-runner recipes](#task-runner-recipes).
- **Binaries**, and any program an interpreter reads from stdin.
- **Obfuscation and computed commands.** A command assembled at run time, a script that decodes its own payload, a path held in a variable (`bash "$S"`).
- **Check-then-use.** The file is read when the hook runs. If it changes before the shell reads it, or another process rewrites it in between, the verdict was about different text. A script that rewrites itself, or one a background process edits, is the same case.
- **Files read by other launchers.** `find -exec sh {}`, `xargs sh`, a PowerShell script, a cron entry or a service unit the agent installs.
- **Languages beyond shell, `python`, `node`, `perl` and `ruby`**, and calls those four languages make through a wrapper function the scan cannot see through. A name bound once to a literal is followed; anything built at run time is not.

## Defense in depth

Damage control is one layer. Keep the others:

- Run the agent as a normal user, never root.
- Keep backups of anything you cannot regenerate.
- Commit often. Git history undoes most agent mistakes.
- Keep the audit log (`logs/damage-control/<date>.jsonl` under `~/.damage-control/` or `$DAMAGE_CONTROL_HOME`, one JSON line per decision) and read it when something surprises you.
- Turn on Claude Code's sandbox and close its unsandboxed retry ([pairing with the sandbox](sandbox.md)). Prefer a container or VM when you need stronger containment. This tool is not that.

## Reporting a bypass

A bypass of a shipped rule that this document says should be caught is a vulnerability. A gap in the [declared residuals](#declared-residuals) is a known limit, not a vulnerability, though a way to close one is welcome.

Report a bypass **privately**, through the "Report a vulnerability" button on the repository's Security tab. Do not open a public issue. See [SECURITY.md](../SECURITY.md) for the process and response targets.

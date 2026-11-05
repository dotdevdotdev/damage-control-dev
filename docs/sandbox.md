# Pairing with the Claude Code sandbox

damage-control-dev and Claude Code's own sandbox are two different layers. Each covers a gap the other has, so run both.

- [The two layers](#the-two-layers)
- [What the sandbox leaves uncovered](#what-the-sandbox-leaves-uncovered)
- [Recommended settings](#recommended-settings)
- [What `doctor` reports](#what-doctor-reports)
- [Verification status](#verification-status)

## The two layers

| Layer | Question it answers | How |
|---|---|---|
| This hook | Should this command start? | Reads the command text (and the file it runs) before it executes, and blocks or asks. |
| Claude Code sandbox | What can this command reach once it is running? | An operating-system boundary around shell commands and the processes they start, with filesystem and network limits. |

Text rules cannot stop a command whose text looks fine. An operating-system boundary cannot tell a deliberate `rm` in the working directory from a mistaken one, because both are allowed writes there. The hook can.

The sandbox is off by default, runs on macOS, Linux and WSL2, and covers shell commands only. Source: [Sandboxing](https://code.claude.com/docs/en/sandboxing).

## What the sandbox leaves uncovered

From the same page: "The sandbox covers shell commands only. Claude's file tools, MCP servers, and hooks run outside it." The table says which of those gaps this hook screens.

| Left uncovered by the sandbox | Screened by this hook? |
|---|---|
| Built-in file tools (`Read`, `Edit`, `Write`) follow permission rules, not the sandbox | Yes, on the path (and script-looking text written). See [coverage](coverage.md). |
| `WebFetch` and `WebSearch` follow permission rules; a `denyRead` entry does not stop the `Read` tool and `allowedDomains` does not limit `WebFetch` | No. They have no hook event here. Use Claude Code permission rules. |
| MCP servers run outside the sandbox | Partly. Path arguments of MCP tool calls and the `mcp-tools` policies are judged; what the server does is not. |
| Command hooks (this hook included), local MCP servers, plugin monitors, LSP servers, the status line command and `apiKeyHelper` run "with your full access" | The hook protects its own registration and files from edits through the tools it judges ([control plane](threat-model.md#the-control-plane-and-the-kill-switch)). It does not judge other processes Claude Code starts. |
| Reads: by default "most of the machine, including credential files such as `~/.ssh` and `~/.aws/credentials`" | Yes. Reads of `.env` files, SSH and cloud credentials and private keys are blocked or asked, in `Bash` and in the read tools. |
| Environment variables are inherited from Claude Code, secrets included | No. |
| Commands you type with a leading `!` (usually unsandboxed) | No. See [what it does not protect against](threat-model.md#what-it-does-not-protect-against). |
| Commands in `excludedCommands` and unsandboxed retries | The retry is a Bash call like any other and is judged by its text. Close it with the settings below. |

Source for the first six rows: [Sandboxing, what runs outside the sandbox and default access](https://code.claude.com/docs/en/sandboxing).

## Recommended settings

Put this in `~/.claude/settings.json` (or a project file). Add it to the keys already there; do not replace the file.

```json
{
  "sandbox": {
    "enabled": true,
    "allowUnsandboxedCommands": false
  },
  "permissions": {
    "ask": ["Bash(dangerouslyDisableSandbox:true)"]
  }
}
```

What each key does, per the official docs:

- `sandbox.enabled`: turns the sandbox on; it is off by default. [Sandboxing, key settings](https://code.claude.com/docs/en/sandboxing), [settings reference](https://code.claude.com/docs/en/settings-reference).
- `sandbox.allowUnsandboxedCommands`: `false` disables the unsandboxed retry ("strict sandbox mode"). With it false, Claude Code ignores the `dangerouslyDisableSandbox` parameter. [Sandboxing](https://code.claude.com/docs/en/sandboxing).
- `permissions.ask` rule `Bash(dangerouslyDisableSandbox:true)`: prompts on every retry, including in auto and `bypassPermissions` modes, and takes precedence over a matching allow rule. It is a second guard in case a managed or project file reopens the retry. [Sandboxing](https://code.claude.com/docs/en/sandboxing), permission rule syntax in [Configure permissions](https://code.claude.com/docs/en/permissions).

Also worth knowing:

- `sandbox.failIfUnavailable: true` makes Claude Code exit at startup when the sandbox cannot run; by default it runs commands unsandboxed. [Sandboxing](https://code.claude.com/docs/en/sandboxing).
- Settings merge across files in the order managed, command line, project local, shared project, user; lists such as `permissions.ask` combine rather than override. [Settings](https://code.claude.com/docs/en/settings).
- The sandbox docs say not to rely on its restrictions alone to stop a malicious command, because in auto-allow mode such a command can run without a prompt. This is a reason to keep the hook as well.

## What `doctor` reports

`damage-control-dev doctor` ends with informational `sandbox:` lines. They are never scored and never change the exit code.

| Line | Meaning |
|---|---|
| `sandbox: enabled` then `unsandboxed retry is closed` | `sandbox.enabled` is true and `allowUnsandboxedCommands` is false. |
| `sandbox: enabled` then `unsandboxed retry is OPEN` | The retry is allowed. A further line says whether the ask rule above is set. |
| `sandbox: not enabled` / `explicitly disabled` | No file read turns the sandbox on. |
| `sandbox: <path> was not read (...)` | The file is not valid JSON or not an object. Nothing is guessed from it. |
| `sandbox: no settings file found` | None of the files exist; the state is unknown. |

It reads, read-only, `~/.claude/settings.json`, `.claude/settings.json` and `.claude/settings.local.json` in the current directory, and applies them in that precedence. With `--settings PATH` it reads only that file. It does not read managed settings, the command line, or what a running session loaded; use `/status` inside Claude Code for that.

## Verification status

Checked against the official pages on 2026-11-05:

- Verified: the key names `sandbox.enabled`, `sandbox.allowUnsandboxedCommands`, `sandbox.failIfUnavailable` and `permissions.ask`; the `Bash(dangerouslyDisableSandbox:true)` ask rule and its behavior; what runs outside the sandbox; default read access; settings precedence.
- Not verified: the default value of `sandbox.allowUnsandboxedCommands`. The reference index lists the key without a default; `doctor` treats anything other than `false` as open. Managed-settings file locations on each platform were not checked, which is why `doctor` does not read them.

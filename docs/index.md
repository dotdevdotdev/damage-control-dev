# damage-control-dev documentation

A guardrail for AI coding agents: a Claude Code `PreToolUse` hook that blocks or asks before destructive commands, secret access and protected-path writes. It is a seatbelt, not a sandbox. Claude Code on macOS and Linux, Python 3.9 or newer.

Start with the [README](../README.md) for install and the commands you will use every day.

| Page | Read it to learn |
|---|---|
| [Threat model](threat-model.md) | What it catches, what it does not, where it fails open, and how to report a bypass. |
| [Coverage](coverage.md) | Which Claude Code tools are judged, and whether each can block, ask, or both. Generated from the code. |
| [Rule authoring](rule-authoring.md) | Writing rules, tooldefs and path lists; the policy file; groups and packs; the path allowlist. |
| [Extending](extending.md) | Host profiles, how the hook is registered and why it fails closed, break-glass, the installer. |

Also: [SECURITY.md](../SECURITY.md) (reporting a vulnerability) and [CONTRIBUTING.md](../CONTRIBUTING.md).

## Common questions

- *Will it stop a command I type with `!`?* No. See [what it does not protect against](threat-model.md#what-it-does-not-protect-against).
- *How do I see what it would decide?* `damage-control-dev check "<command>"`; see [try a rule](rule-authoring.md#try-a-rule-check-and-rules).
- *How do I turn on the AWS rules?* `damage-control-dev packs enable aws`, from your own terminal; see [groups and packs](rule-authoring.md#groups-and-packs).
- *Every tool call is blocked and I cannot fix it.* Use [break-glass](extending.md#break-glass).

# damage-control-dev

A guardrail layer for AI coding agents. It runs as a Claude Code `PreToolUse` hook and **blocks or asks before destructive commands, secret access, protected-path writes and risky MCP calls**, before the tool runs.

It is a seatbelt, not a sandbox. See [What it is not](#what-it-is-not).

```
uv tool install damage-control-dev      # or: pipx install damage-control-dev
damage-control-dev init                 # register the hooks, self-test them, record the install
damage-control-dev status               # read-only drift report
```

Supports **Claude Code on macOS and Linux**, Python 3.9 or newer. Nothing else is supported or planned.

## What it does

- Guards Bash, Edit, Write, Read and MCP tool calls through one policy ladder (allow, ask, block).
- Re-scans wrapped commands as commands in their own right: `ssh host "..."`, `sh -c`, database clients (`psql -c`, `mysql -e`), `git -c` keys that run programs.
- Protects its own control plane: the hook scripts, the settings that register them, and its policy file cannot be edited by the agent it guards.
- Fails closed: any crash or import failure in the hook exits 2 (block), and `init` registers the hook with `onFailure: block` (Claude Code 2.1.295 or newer) so a missing interpreter blocks the call instead of silently allowing it.
- Unattended mode: when no human can answer a prompt, an `ask` becomes a block unless a rule carries an explicit grant.
- Rules ship as groups that are on by default (core, git, registry, payloads, remote, MCP tools, control plane) and opt-in vendor packs: `aws`, `gcp`, `firebase`, `cloud-hosting`, `databases`, `containers`, `infrastructure`, `publish`, `tmux`. Every rule has a frozen, stable id.
- Offline: after `init` nothing touches the network.

```
damage-control-dev check "git push --force origin main"   # what would the hooks decide?
damage-control-dev rules                                   # list enforced rule ids
damage-control-dev packs                                   # list packs; enabling is human-terminal only
damage-control-dev doctor --fix                            # self-test and repair
damage-control-dev uninstall                               # remove exactly our entries
```

## What it is not

- Not a sandbox, and not a boundary against a determined adversary. A process running as the same OS user can edit anything this tool can.
- Only as strong as the harness's hook surface: commands you type yourself with `!`, tools that have no hook event, and a hook that times out are outside its reach.
- No network egress filtering, containment or resource limits.
- Expect false positives and false negatives. The policy is: ask, then learn.

See [docs/threat-model.md](docs/threat-model.md).

## Where things live

Everything the installer keeps is under `~/.damage-control/` (or `$DAMAGE_CONTROL_HOME`):

- `damagecontrol.yml`: the protected policy (kill switch, `packs:`, `disabled_groups:`)
- `damage-control/`, `tooldefs/`: your own rule overlays
- `state/install.json`: what `init` recorded (interpreter, ruleset digest, per-scope write hash); `state/backups/` holds first-write backups of your settings file
- `bin/damage-control-breakglass`: a stdlib-only script that unregisters the hooks if the Python environment is ever broken

A policy with no `packs:` key loads the default groups and no vendor packs; an unreadable policy loads everything.

If the environment breaks (for example a `uv tool install --force` interrupted mid-upgrade) and the hook cannot start, every tool call is blocked by design. Run `python3 ~/.damage-control/bin/damage-control-breakglass unregister` from a normal terminal, then reinstall and run `init` again.

## Docs

- [docs/threat-model.md](docs/threat-model.md): what it protects against and the residuals
- [docs/coverage.md](docs/coverage.md): which tools are covered and how
- [docs/rule-authoring.md](docs/rule-authoring.md): writing rules, packs and overlays
- [docs/extending.md](docs/extending.md): profiles, the hook runtime, registration and repair

## Security

A bypass of a shipped rule that the threat model says should be caught is a vulnerability. Report it privately, see [SECURITY.md](SECURITY.md).

## License

Apache-2.0. Contributions are signed off under the DCO, see [CONTRIBUTING.md](CONTRIBUTING.md).

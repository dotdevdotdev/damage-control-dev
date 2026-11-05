# Extending: profiles, the hook runtime and registration

For people who embed damage control in another tool (a **host**) or who want to know exactly what runs when Claude Code calls the hook.

- [Profiles](#profiles)
- [Example: a host called acme](#example-a-host-called-acme)
- [Example: AgentWire, an embedding host](#example-agentwire-an-embedding-host)
- [The decision seam: Guard and adapter](#the-decision-seam-guard-and-adapter)
- [Registration](#registration)
- [Why the hook fails closed](#why-the-hook-fails-closed)
- [Break-glass](#break-glass)
- [The installer](#installer)

## Profiles

The engine knows what is dangerous in general. A host adds what is dangerous **around itself**: its own config files, commands that must never run through an agent, the environment variables its scheduler sets. A `Profile` (`damage_control.profile.Profile`) is that whole surface as plain data. The engine has no host names in its logic.

A profile only ever **adds**. The generic control plane (project `.damagecontrol.yml`, `~/.claude/settings.json`, `~/.claude/hooks/*`, the policy file, the profile manifest itself) is a kernel that a profile cannot remove or reorder. The control-plane and protected-command checks still run before the kill switch.

| Field | What it adds |
|---|---|
| `name` | Label shown by `status --json`. Default `generic`. |
| `config_dir`, `config_dir_env` | The config home (default `~/.damage-control` and `DAMAGE_CONTROL_HOME`). It holds the policy file, `state/`, `bin/`, `logs/` and the overlay directories. The env var relocates everything except the policy file. |
| `protected_paths` | More control-plane paths. Writes are blocked even with the kill switch off. |
| `control_plane_words` | Names a program might use to build a control-plane path at run time. |
| `benign_path_patterns` | Regex alternatives for directories agents write by design (whole path segment). |
| `home_alias` | Fixed stand-in for `$HOME` when judging what a `~` allowlist entry covers. |
| `protected_commands` | `(regex, reason)` pairs for commands that must never run through an agent. No allowlist, `# ask:` comment or kill switch applies. |
| `unattended_env`, `unattended_allow_env` | Env var names for unattended mode and per-run grants. Defaults `DAMAGE_CONTROL_UNATTENDED` and `DAMAGE_CONTROL_UNATTENDED_ALLOW`. |
| `default_unattended_allow` | Rule ids granted to unattended runs by default. The engine ships none. |
| `unattended_grant_hint` | First half of the sentence telling a blocked unattended run how to get a grant (`{rule_id}` is filled in). |
| `unattended_block_notifier` | An argv run detached when an unattended action is blocked; the event arrives as JSON on its stdin: `{"event": "unattended_block", "reason", "rule_id", "command"}`. |
| `audit` | An `AuditSpec`: `log_dir`, `session_env`, `agent_env`, `sessions_dir`. |
| `extra_rules_dirs` | Absolute directories of rule files (JSON, or YAML a human wrote), merged after the bundled rules. |
| `mcp_command_templates` | How an outbound MCP tool maps to the shell command it runs, so the same rule that matches the shell form matches the tool call. |
| `groups`, `group_layer_rules`, `default_packs` | The host's own groups and packs, rule files attached to generic groups, and the packs that are on when the policy has no `packs:` key. |

### Profiles are data

A profile reaches the hook as a JSON manifest, never as an import. The host's installer writes it with `dump_profile`, and the registered hook command names it with `--profile PATH`. The hook therefore never imports the host. `load_profile` rejects unknown fields and anything that is not a JSON object with `ProfileError`, and a manifest that cannot be read is never answered with the generic profile.

`check`, `rules`, `packs`, `groups`, `init`, `status`, `doctor` and `uninstall` all take `--profile PATH`. A host's install record lives in the profile's own config home, so pass the same `--profile` to `status`, `doctor` and `uninstall`.

Extension rule sources are held to a rule: an `allowedPaths` entry in an extension's rule file that would re-permit the control plane is dropped with a load failure. An extension cannot loosen the thing it extends.

## Example: a host called acme

A made-up host that guards `~/.acme/credentials/`, forbids `acme auth reset`, and adds a rule that asks before a production deploy. Each step below was run against the package.

The rule file the profile points at:

```yaml
# /opt/acme/rules/acme.yaml
bashToolPatterns:
  - id: acme.deploy-prod
    pattern: '\bacme\s+deploy\s+--prod\b'
    reason: acme deploy to production
    ask: true
    anchored: true
```

The installer script writes the manifest:

```python
from pathlib import Path
from damage_control.profile import Profile, dump_profile

profile = Profile(
    name="acme",
    config_dir="~/.acme",
    config_dir_env="ACME_HOME",
    protected_paths=("~/.acme/credentials/*",),
    protected_commands=((r"\bacme\s+auth\s+reset\b", "acme auth reset is a human-only command"),),
    extra_rules_dirs=("/opt/acme/rules",),
)
Path("/opt/acme/profile.json").write_text(dump_profile(profile))
```

Then:

```
$ damage-control-dev check --profile /opt/acme/profile.json "acme deploy --prod"
ask: acme deploy to production [acme.deploy-prod]
$ damage-control-dev check --profile /opt/acme/profile.json "acme auth reset"
block: acme auth reset is a human-only command [core.protected-command]
$ damage-control-dev check "acme deploy --prod"
allow: No patterns matched
$ damage-control-dev init --profile /opt/acme/profile.json
registered: 9 matchers in ~/.claude/settings.json (scope user, fail-closed, interpreter …)
```

The last line of `check` shows why the profile must be named in the registration: without it the hook knows nothing about acme.

`init` refuses to rewrite an entry that another installer owns. After the acme install, a plain `damage-control-dev init` stops with `REFUSED: … already registers damage control for profile … not (none): another installer owns it`, so two installers cannot silently take each other's registration.

## Example: AgentWire, an embedding host

AgentWire, a terminal-session manager for AI agents, embeds damage control through exactly this API. Its installer builds a `Profile` carrying its own config files, its own protected commands, its scheduler's unattended environment variables, its own rule files and its default packs. It then writes the manifest and runs this package's `init --profile` against it. The package knows nothing about AgentWire; the manifest is the whole interface.

## The decision seam: Guard and adapter

Two modules hold the decision, and both are free of I/O in their core:

- **`policy.Guard.decide(ToolCall, Context) -> Verdict`** is the ladder that turns an engine finding into allow, ask or block: bypass demotion, the unverifiable carve-out, the unattended fail-closed path with its grants, the kill switch, and MCP screening. It is pure. It returns the audit row, the stderr lines and any notification as data, and it takes the engine as an argument, so tests can drive it with a stub engine.
- **`adapter`** turns the hook payload into a `ToolCall` and `Context`, and `render(verdict)` is the one place a decision becomes an exit code. Each hook is: load config, parse, decide, render.

Rule sources are merged additively in precedence order: bundled rules, profile layers (`extra_rules_dirs`), then the user's overlay. A rule id repeated across sources is recorded as a load error, with both rules still live.

The engine modules need only the standard library. PyYAML is imported lazily, and only to read a file a human wrote.

## Registration

`damage-control-dev init` writes one entry per matcher into `settings.json` using the exec form, which Claude Code runs without a shell:

```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "/path/to/venv/bin/python",
      "args": ["-I", "-m", "damage_control.hook", "bash"],
      "timeout": 30,
      "onFailure": "block"
    }
  ]
}
```

The nine matchers and their hook kinds are in [coverage](coverage.md). `args` gains `--profile PATH` when a profile is used. Our entries are recognized by the module name `damage_control.hook` in `args` and by nothing else; every other hook in the file is left alone.

Before it writes, `init` runs the same command as a self-test. Every hook kind must exit 0 on a tool it does not gate, and Bash must block `rm -rf`. If the self-test fails, nothing is registered.

## Why the hook fails closed

Python exits 1 when an import fails or an exception escapes. Claude Code treats exit 1 as "no decision", so the call runs. The only exit that stops a call is 2. The hook is layered so that each way of failing ends in 2:

1. **`damage_control/hook.py` imports only `os` and `sys`.** Any failure importing the engine, or a module that exits 0 during import, becomes exit 2. An exception hook does the same for anything that escapes.
2. **`-I` isolates the interpreter.** The working directory is the agent's to write, and `python -m` would otherwise put it first on `sys.path`. `-I` also drops `PYTHON*` variables and the user site directory.
3. **PyYAML is imported lazily**, and only for a human's YAML overlay. A broken or missing PyYAML never stops the bundled JSON rules from enforcing.
4. **Anything before Python runs** (interpreter gone, package gone) is covered by `onFailure: block`, which makes Claude Code refuse the tool call. That needs Claude Code 2.1.295 or newer.

Layer 4 has a price. If the environment breaks, for example a `uv tool install --force` interrupted mid-upgrade, every tool call is blocked, including the ones you would use to repair it. That is what break-glass is for.

The timeout side (what happens when a hook is too slow) is in the [threat model](threat-model.md#fails-open).

## Break-glass

`init` copies a stdlib-only script to `<config home>/bin/damage-control-breakglass` (`~/.damage-control/bin/` by default). It lives outside the virtual environment on purpose. Run it with the system `python3` from an ordinary terminal, **not** through Claude Code:

```
$ python3 ~/.damage-control/bin/damage-control-breakglass status
9 damage-control hook entries in ~/.claude/settings.json
  interpreter /path/to/venv/bin/python: ok
$ python3 ~/.damage-control/bin/damage-control-breakglass unregister
Removed the damage-control hooks from ~/.claude/settings.json (backup: …)
DAMAGE CONTROL IS NOW OFF. Repair the install, then re-register:
  damage-control-dev init
```

`unregister` removes exactly our entries, backs the file up first (`settings.json.breakglass.bak`), writes atomically, and refuses a settings file that does not parse. It leaves damage control off until you reinstall and run `init` again.

## Installer

`damage-control-dev init|status|doctor|uninstall` live in `damage_control.cli` and `damage_control.install`.

**`init`**

- Edits the settings file through one structural JSON merge: parse, merge keyed on the module name, atomic write, re-read to verify, and detection of a concurrent writer. A file that does not parse is refused and left byte-identical.
- Refuses: Claude Code older than 2.1.295 (no `onFailure`) unless you pass `--fail-open`; an install older than the recorded one unless `--force`; an editable, VCS or `uvx` source unless `--allow-dev-source`; and an entry owned by a different `--profile`.
- Has `--dry-run` (print the diff, write nothing) and `--refresh` (print and acknowledge the ruleset diff by rule id; a removed rule, a lowered tier, a new allow path or a new default grant is marked `!!`).
- Scopes: `user` (`~/.claude/settings.json`), `project` (`.claude/settings.json` in the working directory) and `managed` (a drop-in under `/Library/Application Support/ClaudeCode/managed-settings.d/` on macOS or `/etc/claude-code/managed-settings.d/` on Linux). `managed` is a dry run unless you pass `--apply`.
- Records `state/install.json` under the config home: interpreter, ruleset digest by rule id, and a per-scope hash of what it wrote. `uninstall` restores the original bytes only while the file is still exactly what `init` wrote, and otherwise removes just our keys.

**`status`** is read-only and prints one line per finding, `[ok]`, `[..]` (informational) or `[!!]` (a problem).

```
$ damage-control-dev status
[ok] 9 matchers registered correctly in ~/.claude/settings.json
[ok] interpreter /path/to/venv/bin/python runs and imports damage_control
[ok] ruleset matches the last acknowledged one
[ok] protected paths are owner-writable only
```

**`doctor`** is `status` plus a self-test, the Claude Code version check and informational `sandbox:` lines ([sandbox pairing](sandbox.md#what-doctor-reports); never scored). `doctor --fix` re-runs `init` to repair a drifted registration. `--json` on `status` and `doctor` emits `{ok, version, profile, findings}`.

**Exit codes** for `init`, `status`, `doctor` and `uninstall`: `0` fine, `1` a refusal (`REFUSED: …` on stderr) or a `[!!]` finding, `2` bad command-line usage. `check`, `rules` and `packs|groups list` return `0`.

**`uninstall`** removes exactly our entries and prints `DAMAGE CONTROL IS NOW OFF for this scope.` `--purge` also deletes the policy file, the overlay directories and the install state.

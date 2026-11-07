# The `agentwire` pack

An optional pack for machines that run the agentwire orchestrator, a manager of parallel agent sessions in tmux. It is **off until you turn it on**, it is plain data, and it does not depend on agentwire: nothing in it calls agentwire, reads its files or expects it to be installed, and agentwire does not need this library. The two work together when both are present. Neither sets the release cycle of the other.

- [Enable it](#enable-it)
- [What it protects](#what-it-protects)
- [Unattended sessions](#unattended-sessions)
- [How a pack carries code-level protections](#how-a-pack-carries-code-level-protections)
- [Tests](#tests)

## Enable it

From your own terminal, the same way as any other pack (see [groups and packs](rule-authoring.md#groups-and-packs)):

```
damage-control-dev packs enable agentwire
```

The command refuses without a TTY on stdin, so an agent's shell tool cannot run it. `packs disable agentwire` turns it off again. The hook reads the policy file on every call, so nothing needs reinstalling.

Without a decision the pack is not loaded: `packs list` shows `off agentwire`, and the commands below are judged by the generic rules alone. The pack and the generic `tmux` pack are separate; `packs enable tmux` turns on the `tmux kill-server` and `kill-session -a` rules.

## What it protects

| Area | Entries | Tier |
|---|---|---|
| Secrets | `~/.agentwire/credentials/`, `api-keys/`, `secrets/`, `tokens/`, `.env`, `*.key`, `*.pem` | zero access (no read, write or delete); the owner's `~/.agentwire/.env` stays readable and writable |
| State | `~/.agentwire/`, `sessions/`, `hooks/`, `settings.json`, and a project's `.agentwire/` and `.agentwire/session.json` | no delete |
| Control plane | the damage-control policy and profile files, hook scripts and rule files, the break-glass script and install record under `~/.agentwire/`, plus `scheduler.yaml`, `config.yaml` and any `*.agentwire.tasks.yml` | write-protected in code: no allowlist entry, `# ask:` or kill switch re-permits them |
| Commands | `agentwire destroy`, `agentwire … --force … remove`, `tmux kill-session` of an agentwire session, a recursive or forced `rm` whose target is the `.agentwire` directory itself | block |
| Host-only commands | `agentwire tasks promote`, `agentwire safety packs\|groups enable\|disable`, `agentwire safety migrate` (not `--dry-run`) | block, with no override |
| Outbound | `agentwire email`, `agentwire quo` | ask; fail closed when unattended |
| MCP tools | `worktree_remove`, `worktree_prune`, `session_kill`, `pane_kill`, `session_recreate`, `machine_remove` | ask |

The control-plane files split the same way as the rest of the library: the path lists in the pack make the entries visible in `status` and `rules`, and the `profile:` fragment below makes them absolute.

A recursive `rm` is judged by its target, not by whether it mentions the directory: removing one file inside `~/.agentwire/` falls through to the ordinary `rm` rules with an honest reason, and only a recursive or forced `rm` of the directory itself is blocked by name. Quoted text that only mentions a protected path or an `agentwire` verb (a commit message, an `agentwire msg send` body) is data, not an operand.

## Unattended sessions

A session is **unattended** when its environment carries the marker the pack declares. In an unattended session an `ask` fails closed (block and notify) unless the rule id is granted.

| Name | Meaning |
|---|---|
| `AGENTWIRE_UNATTENDED` | `1` marks the session unattended. The neutral `DAMAGE_CONTROL_UNATTENDED` is a plain install's name and is not read while this pack is on. |
| `AGENTWIRE_UNATTENDED_ALLOW` | A comma-separated list of rule ids, or a JSON array when an entry is scoped, granted to this session on top of the defaults. |
| `AGENTWIRE_SESSION_ID`, `AGENTWIRE_AGENT_ID` | Recorded in audit rows. |

Default grants, given without a per-task entry. Each is an `ask`-tier rule; hard blocks are unaffected.

`git.add`, `git.add-u`, `git.commit`, `git.push`, `gh.pr-create`, `outbound.agentwire-email`, `tooldef.uv-run-a-script-in-project-environment`, `tooldef.uv-run-a-command-in-project-environment`.

`outbound.agentwire-quo` and every `mcp.agentwire.*` policy are not granted by default. The hint printed on a blocked run says to add the id to a task's `unattended_allow` in `.agentwire.tasks.yml`.

An agentwire install that enables the pack and sets the same variables judges as it did when agentwire shipped these rules itself. The corpus rows with `pack-outbound` ids replay that through the real hook.

## How a pack carries code-level protections

Rule files normally hold lists and patterns. The pack's file also has a top-level `profile:` section, a fragment of the [host profile](extending.md) that is merged in only while the pack is on. It can add: `protected_paths`, `protected_path_reasons`, `control_plane_words`, `benign_path_patterns`, `protected_commands`, `message_commands`, `data_consumers`, `default_unattended_allow`, `mcp_command_templates`, `audit`, and set `unattended_env`, `unattended_allow_env` and `unattended_grant_hint` while the host left the generic default alone. It cannot move the config home or the policy file, change the groups or add rule directories; a fragment with any other field is refused, not ignored. Only bundled files are read for it: a file in a user's overlay directory is not.

A host that installs its own profile keeps working unchanged. Its profile is the base and the fragment is added to it.

## Tests

The pack is covered by the `pack-state`, `pack-commands` and `pack-outbound` classes of the [conformance corpus](conformance.md), which replay allow and block sides, the unattended cases and the same commands with the pack off through the real hook, and by `tests/test_agentwire_pack.py`, which also checks the file-tool and MCP hooks and that no file of the library outside the pack's own files and corpus rows contains the name.

# Rule authoring

How rules, tooldefs, groups, packs and the policy file fit together, and how to add your own.

- [Where things live](#where-things-live)
- [Try a rule: `check` and `rules`](#try-a-rule-check-and-rules)
- [Writing a rule](#writing-a-rule)
- [Anchored or not](#anchored-or-not)
- [Path lists](#path-lists)
- [Writing a tooldef](#writing-a-tooldef)
- [The policy file](#the-policy-file)
- [Groups and packs](#groups-and-packs)
- [The path allowlist](#the-path-allowlist)
- [Order of evaluation](#order-of-evaluation)
- [When a file does not parse](#when-a-file-does-not-parse)
- [Contributing a bundled rule](#contributing-a-bundled-rule)

## Where things live

| What | Where |
|---|---|
| Bundled rules (YAML source, JSON the hook reads) | `src/damage_control/rules/` in the repo, `damage_control/rules/` in the install |
| Bundled tooldefs | `src/damage_control/tooldefs/` |
| Your rule overlays | `~/.damage-control/damage-control/*.yaml` |
| Your tooldef overlays | `~/.damage-control/tooldefs/*.yaml` |
| The protected policy file | `~/.damage-control/damagecontrol.yml` |
| A per-project policy file | `.damagecontrol.yml`, found by walking up from the working directory |

`$DAMAGE_CONTROL_HOME` relocates the **overlay directories**, `state/`, `bin/` and `logs/`. It does **not** move the policy file, which is always `~/.damage-control/damagecontrol.yml`.

The bundled rules are shipped as JSON next to their YAML sources, so a hook never needs to parse YAML to enforce them. YAML (via PyYAML, a dependency) is read only for files a human wrote: overlays and policy files.

An overlay file **replaces the bundled file of the same name** and adds to the rest. The bundle is never dropped. To change one bundled file, copy it from `src/damage_control/rules/` into your overlay directory and edit the copy; to add rules, use a new file name. Files are merged in file-stem order.

## Try a rule: `check` and `rules`

`damage-control-dev check "<command>"` prints the decision and rule id for a shell command. It always exits 0, so read the first word, not the exit code.

```
$ damage-control-dev check "git push --force origin main"
block: git push --force (use --force-with-lease) [git.git-push-force-use-force-with-lease]
$ damage-control-dev check "git commit -m wip"
ask: Git: Create a commit [git.commit]
$ damage-control-dev check ls
allow: No patterns matched
```

`damage-control-dev rules` lists every enforced command rule as `<tier> <id>  (<source>)`, after packs, groups and overlays are applied. `--json` gives the same as a list of `{id, tier, source}`.

```
$ damage-control-dev rules | head -4
block core.rm-with-recursive-or-force-flags  (core)
block core.rm-with-recursive-flag  (core)
block core.rm-with-force-flag  (core)
block core.sudo-rm  (core)
```

`check` and `rules` cover command rules and tooldefs. To test a path list, feed the hook directly:

```
$ echo '{"tool_name":"Read","tool_input":{"file_path":"/tmp/server.pem"},"cwd":"/tmp"}' | python -I -m damage_control.hook read
SECURITY: Blocked read of zero-access path *.pem (no read access): /tmp/server.pem
```

## Writing a rule

A rule file has any of these top-level keys: `bashToolPatterns`, `zeroAccessPaths`, `readOnlyPaths`, `noDeletePaths`, `allowedPaths` and `mcpToolPolicies`. The most common is `bashToolPatterns`:

```yaml
# ~/.damage-control/damage-control/myapp.yaml
bashToolPatterns:
  - id: myapp.destroy
    pattern: '\bmyapp\s+destroy\b'
    reason: myapp destroy removes the production app
    anchored: true

  - pattern: '\bmyapp\s+restart\b'
    reason: myapp restart
    ask: true
    anchored: true
```

Result:

```
$ damage-control-dev check "myapp destroy now"
block: myapp destroy removes the production app [myapp.destroy]
$ damage-control-dev check "myapp restart"
ask: myapp restart [myapp.myapp-restart]
```

Fields:

| Field | Meaning |
|---|---|
| `pattern` | A regular expression, matched case-insensitively. |
| `reason` | Shown to the agent and the human when the rule fires. |
| `id` | The rule's stable name. Optional; without it the id is `<file stem>.<slug of the reason>` (the second rule above got `myapp.myapp-restart`). Set it explicitly on any rule you reference elsewhere. |
| `ask` | `true` makes a match prompt a human instead of blocking. Omit it for a hard block. |
| `anchored` | See [Anchored or not](#anchored-or-not). |
| `bypassable` | A block that is lifted when every path operand is covered by an [allowlist](#the-path-allowlist) entry with the matching operation. Used by plain `rm`, `rmdir` and `trash`. |

Rules to keep in mind:

- **Ids are the public name of a rule.** `disabled_rules` and `unattended_allow` refer to them. Two rules with the same id across all sources are a load error: both stay live and the duplicate is recorded.
- **Use `\b` and `\s+`.** `\brm\b` does not match `format`; `git\s+push` matches `git push` with any spacing.
- **A block outranks an ask.** If one command matches both, the block wins regardless of file order.
- **Some bundled rules carry a `pattern_src:` key.** It is a note about how the pattern was derived; the engine never reads it. Only `pattern:` is matched.
- **Flags can follow operands.** GNU tools accept `rm foo -rf`, so a pattern that only looks at flags before the first operand misses it. Look at how `core.rm-with-recursive-or-force-flags` is written in `rules/core.yaml` when you write a rule for such a tool.

## Anchored or not

An **unanchored** rule matches the raw command string. It fires on text that merely *mentions* the operation: a commit message, an `echo`, a `grep` for the rule's own reason.

An **anchored** rule (`anchored: true`) matches only at a command position. Quoted tokens that contain whitespace and heredoc bodies are blanked first, so prose cannot trigger it, while quoting tricks on the command itself still normalize (`"rm" -rf`, `r\m`, `R=rm; $R`). `sh -c "…"` payloads are rescanned.

Set `anchored` on every rule. The default is unanchored.

| Use | When |
|---|---|
| `anchored: true` | The danger is the command's own verb: `rm`, `git push --force`, `terraform destroy`. |
| `anchored: false` | The danger arrives *inside* another command's quoted payload: SQL given to `psql -c`, code given to `python -c`, a command given to `ssh host "…"`. |

Decide per **file**, not per rule. Masking blanks quoted text regardless of position, so a rule meant to read a quoted payload loses exactly what it needs when anchored. The bundled `payloads.yaml` and `remote.yaml` are entirely unanchored for this reason; the other command-prefix files are anchored. Do not mix the two in one file.

Wrapped commands are also judged by the engine, not only by rules: `ssh host "rm -rf /x"` and `sh -c "git push -f"` are rescanned as commands in their own right, so your anchored rules apply to them without a twin.

```
$ damage-control-dev check 'ssh host "rm -rf /var/x"'
block: rm with recursive or force flags [core.rm-with-recursive-or-force-flags]
$ damage-control-dev check 'psql -c "DROP TABLE users"'
block: DROP TABLE [databases.drop-table]
```

## Path lists

Path lists guard files rather than commands. They apply to Read, Grep, Glob, Edit, Write and NotebookEdit calls (by path), and to shell commands that touch the path.

| Key | Blocks | Example entries |
|---|---|---|
| `zeroAccessPaths` | any access: read, write, edit, delete | `~/.ssh/`, `*.pem`, `.env*` |
| `readOnlyPaths` | write, append, edit, move, copy, delete, chmod, truncate | `/etc/hosts`, `*.damagecontrol.yml` |
| `noDeletePaths` | `rm`, `unlink`, `rmdir`, `shred` and moving the path out of place | `/myapp/data/` |

Entries are literal paths (`~` is expanded), directory prefixes (a trailing `/`), or globs (`*.pem`).

```yaml
# ~/.damage-control/damage-control/paths.yaml
zeroAccessPaths:
  - /myapp/secrets/
readOnlyPaths:
  - /myapp/config/production.yaml
noDeletePaths:
  - /myapp/data/
```

```
$ damage-control-dev check "cat /myapp/secrets/k"
block: Zero-access path: /myapp/secrets/ [core.zero-access-path]
$ damage-control-dev check "echo hi >> /myapp/config/production.yaml"
block: Read-only path: /myapp/config/production.yaml [core.read-only-path]
$ damage-control-dev check "rm /myapp/data/x"
block: No-delete path: /myapp/data/ [core.no-delete-path]
```

Path-list hits report the ids `core.zero-access-path`, `core.read-only-path` and `core.no-delete-path` whatever file defined the entry, and they are blocks only (a path is allowed or blocked; there is no ask).

Two things to know:

- **Moving the directory is deleting it.** With `/myapp/data/` in `noDeletePaths`, `mv /myapp/data /myapp/old` is blocked (`No-delete path … (moved out of place)`), while renaming a file *inside* it (`mv /myapp/data/x /myapp/data/y`) is allowed, since a directory entry also holds files the agent writes by design.
- **Pipelines that feed a delete are read.** `find /myapp/data -type f | xargs rm` is blocked like `rm /myapp/data/…`; `xargs rm`, `find … -exec rm` and `rm $(…)` are judged against the paths the producer names.

Deleting inside the Claude Code scratch directory for the current session (`/tmp/claude-<uid>/<project>/<session>/…`, at least three levels below the root) is exempt from the `rm -rf` rules, because that directory is disposable.

## Writing a tooldef

A tooldef describes a tool's command surface. Each `access: write` line becomes an anchored **ask** rule on that command prefix. Use a tooldef when you want to gate "every write verb of this CLI" without writing regular expressions.

```yaml
# ~/.damage-control/tooldefs/mytool.yaml
name: mytool
binary: mytool
commands:
  - id: mytool.deploy
    cmd: "mytool deploy <env>"
    access: write
    description: Deploy

  - cmd: "mytool status"
    access: read
    description: Status
```

```
$ damage-control-dev check "mytool deploy prod"
ask: mytool: Deploy [mytool.deploy]
$ damage-control-dev check "mytool status"
allow: No patterns matched
```

- `cmd` is the fixed prefix. It stops at the first `<placeholder>` or `[optional]` token.
- `access` is `read`, `write` or `blocked`. `write` lines become ask rules; `read` lines carve subcommands out of a shorter write prefix; `blocked` lines are documentation only.
- `id` is optional; without it one is derived (`tooldef.<slug of the description>`). Set one on anything you want to grant in `unattended_allow`.
- Use a rule file instead when the operation needs a grammar, such as a verb after a resource path, that a fixed prefix cannot express.

## The policy file

`~/.damage-control/damagecontrol.yml` is the host-owned policy. It is on the protected control plane: the agent cannot edit it. All keys are optional.

```yaml
enabled: true                 # false is the kill switch
disabled_rules:               # rule ids to turn off
  - core.rsync-delete
unattended_allow:             # rule ids an unattended run may use (see below)
  - core.kill-sigkill
packs:                        # vendor packs that are on
  - aws
disabled_groups:              # default groups that are off
  - outbound
allowed_paths:                # the path allowlist (below)
  - path: "/tmp/scratch/*"
    allow: [delete]
```

A project can have its own `.damagecontrol.yml`. The nearest one, walking up from the working directory, is read. It takes `enabled`, `disabled_rules`, `unattended_allow` and `allowed_paths`; `enabled` in the project file wins over the global one, and the lists are merged. A project file is protected from edits as well.

How the keys behave:

- **`enabled: false`** switches the rules off. The control plane stays protected (see the [threat model](threat-model.md#the-control-plane-and-the-kill-switch)). A missing, unreadable or unparseable policy file leaves `enabled` true.
- **`disabled_rules`** skips those ids entirely. Verified: with `core.rsync-delete` disabled, `check "rsync --delete a b"` reports `allow`.
- **`unattended_allow`** applies only when `DAMAGE_CONTROL_UNATTENDED=1` is set for the session. There, an `ask` becomes a block unless the rule's id is listed. The environment variable `DAMAGE_CONTROL_UNATTENDED_ALLOW` can add ids per run. Hard blocks are never granted. An unverifiable ask (for example `eval`) stays blocked unless its own id, such as `core.ambiguous-command`, is named. An entry can also be a mapping with `id:` and `paths:` to scope the grant to directories.
- **Escape comment.** Ending a command with `# allow: <reason>` makes that one command allowed and records the reason in the audit log. A non-empty reason is required. It does not apply to the control plane. Because it is part of the command text, an agent can write it too, so treat it as an audit marker, not as authorization (see the [threat model](threat-model.md#what-it-does-not-protect-against)).

```
$ damage-control-dev check "rm -rf /tmp/x # allow: scratch dir"
allow: Escape hatch: scratch dir
```

## Groups and packs

Every bundled rule file and tooldef belongs to exactly one **group** or **pack**.

```
$ damage-control-dev groups list
on  control-plane    Protected damage-control/agent config paths
on  core             Filesystem, process and history destruction
on  git              Destructive git operations, gh repo delete + git/gh tooldefs
on  uv               uv run/publish ask-tier (own group: opting out of git must not drop it)
on  registry         npm unpublish + npm publish ask-tier
on  payloads         Rules scanning payloads wrapped in other commands
on  remote           ssh-only remote hazards (reboot, service stop)
on  mcp-tools        Per-tool policy for MCP tool calls
on  outbound         Outward-facing sends (email, SMS, push)

$ damage-control-dev packs list
off aws              AWS CLI
off gcp              gcloud
off firebase         Firebase CLI
off cloud-hosting    Vercel, Netlify, Cloudflare, Heroku, Fly, DO, Supabase
off databases        Database CLIs and SQL
off containers       Docker and Kubernetes
off infrastructure   Terraform, Pulumi, Serverless, SAM
off tmux             tmux kill-server / kill-session -a
off publish          cargo/poetry/twine/pnpm/yarn/gem/mvn publish
```

| Kind | On by default | Who can change it |
|---|---|---|
| Kernel groups: `control-plane`, `core` | always | nobody |
| Default groups: `git`, `uv`, `registry`, `payloads`, `remote`, `mcp-tools`, `outbound` | yes | you can opt out: `groups disable <name>` |
| Packs: `aws`, `gcp`, `firebase`, `cloud-hosting`, `databases`, `containers`, `infrastructure`, `tmux`, `publish` | no | you can opt in: `packs enable <name>` |

`packs enable|disable` and `groups enable|disable` write the policy file. They are **human-terminal only**: without a TTY on stdin they refuse, so an agent's shell tool cannot change them.

```
$ damage-control-dev packs enable aws </dev/null
REFUSED: changing damage-control packs is a policy change; run it from your own terminal.
$ echo $?
1
```

State lives in the policy file as `packs:` and `disabled_groups:`, and the hook reads it on every call, so a change takes effect at once without reinstalling anything. The pack boundary is the vendor CLI, so `databases` carries the migration runners and `containers` carries Docker and Kubernetes. Generic destructive operations (`gh repo delete`, `npm unpublish`) live in default groups, not packs, so a fresh install does not silently lose them.

How an absent or broken file loads:

| Policy file | Loaded |
|---|---|
| No `packs:` key (undecided) | the default groups and **no** packs |
| `packs:` present, even empty | exactly the listed packs |
| Unreadable or unparseable | **every** group and **every** pack |

An unparseable file is never written over, and `packs`/`groups` changes are refused until you fix it.

If you disable a group, rule ids in it stop existing. A `disabled_rules` or `unattended_allow` entry for one of them then does nothing.

## The path allowlist

`allowed_paths` is the one knob that re-permits paths the path lists would block. It lives in the policy file (global) or a project `.damagecontrol.yml` (per project, with paths relative to the project root). Each entry names which operations it permits:

```yaml
allowed_paths:
  - path: "/tmp/scratch/*"
    allow: [delete]
  - path: ".env.development"      # project file: relative to the repo root
    allow: [read, write, edit]
```

Operations: `all`, `read`, `write`, `edit`, `delete`, `move`, `chmod`.

```
$ damage-control-dev check "rm /tmp/scratch/a"
allow: No patterns matched
$ damage-control-dev check "rm /tmp/scratch/a /etc/hosts"
block: rm file deletion (use git clean or manual cleanup) [core.rm-file-deletion-use-git-clean-or-manual-cleanup]
```

- **Every path in a command must be covered.** The second command is blocked because `/etc/hosts` is not on the list.
- **Hard blocks stay.** `allow: all` does not lift a non-bypassable block such as `rm -rf`.
- **It cannot re-permit the control plane by accident.** An entry counts only if it names a protected file or its shape covers it. A location allowance like `/tmp/*` does not, whatever `$HOME` happens to be. Rule files shipped by an extension (a host profile, an overlay) cannot carry an entry that would re-permit the control plane: it is dropped with a load failure.
- **Broad entries are dangerous.** `~/.claude/*` with `allow: all` makes your hook registration agent-writable. Keep entries narrow.

## Order of evaluation

For a shell command, roughly:

1. Control-plane and protected-command checks. These run first and ignore the escape comment and the kill switch.
2. Command rules that block (`ask` absent). Not bypassable.
3. Command rules with `ask: true`. A block found anywhere outranks them.
4. `bypassable` rules, which pass if the allowlist covers every operand.
5. Path lists: `allowedPaths` first, then `zeroAccessPaths`, `readOnlyPaths`, `noDeletePaths`.

What an `ask` does next depends on mode: a prompt for a human, allowed under bypass mode (unless unverifiable), blocked when unattended unless granted. See [How a decision is made](threat-model.md#how-a-decision-is-made).

## When a file does not parse

A rule, tooldef or policy YAML file that does not parse contributes **nothing**. Every protection in it is absent. A skip that says nothing would look the same as a healthy set, so the loader reports it: a `SKIPPED <file>:<line>: <yaml error>` line goes to stderr on every load, and `doctor` reports a file that does not parse as `[!!]`.

Fix the YAML (quote any scalar containing `: `, `|` or `#`) and run `damage-control-dev doctor`.

A bad policy file is handled the other way round: it fails toward protection (kill switch on, all groups and packs loaded) and says so.

## Contributing a bundled rule

See [CONTRIBUTING.md](../CONTRIBUTING.md). In short: put the rule in its pack with an explicit stable `id:`, add one must-block and one must-allow case, and rebuild the JSON the hook reads:

```
python tools/build_rules_json.py src/damage_control/rules src/damage_control/tooldefs
```

CI fails if a committed JSON file differs from its YAML source. Rule ids are frozen: a rename or removal is a changelog entry, never an alias.

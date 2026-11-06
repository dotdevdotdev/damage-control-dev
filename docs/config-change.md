# The settings-change guard (`ConfigChange`)

Claude Code runs a `ConfigChange` hook when a settings file or a skill file changes while a session is running. An exit code of 2 keeps the change from applying to that session. The `PreToolUse` rules see an edit to a settings file only when it arrives as a tool call they recognise; this hook sees the change itself, whatever wrote the file.

- [What was observed](#what-was-observed)
- [Which edits fire it](#which-edits-fire-it)
- [What the guard judges](#what-the-guard-judges)
- [What it does not do](#what-it-does-not-do)
- [Registration, status and doctor](#registration-status-and-doctor)
- [Why there are no corpus rows](#why-there-are-no-corpus-rows)

## What was observed

Everything below was captured from Claude Code 2.1.319 in a scratch project, with a scratch `--settings` file holding a capture hook, `--setting-sources project,local`, and `claude -p` driving a long foreground command while a script changed files. No user or managed settings file was involved.

The payload, one JSON object on stdin (paths shortened):

```json
{
  "session_id": "b54d64af-dec7-49c5-ac76-ba2bdf95a5d5",
  "transcript_path": "/home/user/.claude/projects/<project>/<session>.jsonl",
  "cwd": "/scratch/proj",
  "prompt_id": "05fc6368-2102-4f58-b144-6d00d5be3423",
  "hook_event_name": "ConfigChange",
  "source": "project_settings",
  "file_path": "/scratch/proj/.claude/settings.json"
}
```

The same keys arrived for every event; `source` and `file_path` are the only ones that vary. **The payload carries no file contents and no earlier copy**, so a guard can only judge the file as it is on disk when the hook runs.

`source` values seen: `project_settings`, `local_settings`, `skills` (with `file_path` the `SKILL.md`). `user_settings` and `policy_settings` are in the reference but were not produced: that would mean editing a real user or managed file, which the capture did not do.

Other observations:

- The matcher is a regular expression over `source`: a hook with `user_settings|local_settings` ran for a local change and did not run for a project change.
- A hook that exits 2 stops the change. Claude Code's debug log says only `ConfigChange hook blocked change to <file>`; the hook's stderr is not shown to the user. The reason has to go to the guard's own audit log.
- The file on disk is not touched by a block. Later sessions read it as it is.
- A `env` block in a settings file reaches hook processes: a capture hook read `DC_SPIKE_ENV` from the `--settings` file's `env`.
- Settings hooks in the project file ran in a `-p` session without a trust prompt.
- The registered guard, run by Claude Code itself from `init`'s exec-form entry, allowed a benign edit and refused a `disableAllHooks` write and a write that removed every hook (debug log: `completed with status 2`, then `ConfigChange hook blocked change to <file>`).

## Which edits fire it

Each row is one change made to a settings file in the scratch project while a session ran; `file_path` was the changed file every time.

| Change | Fired | `source` |
|---|---|---|
| Write in place (`python`, shell redirect `>`) | yes | the file's own |
| Write a temp file, then `mv` over the file | yes | the file's own |
| Rewrite with the same bytes | yes | the file's own |
| `touch` only | yes | the file's own |
| Write invalid JSON | yes | the file's own |
| Delete the file | yes | the file's own (the file is gone when the hook runs) |
| Recreate a deleted file | yes | the file's own |
| Replace the file with a symlink to another file | yes | `project_settings` |
| Append to an existing `SKILL.md` | yes | `skills` |
| Create a new `skills/<name>/SKILL.md` | yes | `skills` |
| Edit the file passed with `--settings` | **no** | none |

Two caveats, stated plainly:

- In a first capture run an atomic rename, a delete and a skill edit produced no event, and the same changes fired in a repeat run with timestamps. The first run had stale fixtures from an earlier aborted run, so it is not trusted; the table is the repeat. Treat the watcher as best effort.
- `claude config set` was not exercised. It writes the user settings file, and the capture would have had to run against the real one.

A change made while no session is running fires nothing; the next session simply loads the file. The guard cannot help there, and `status` / `doctor` are the check for that case.

## What the guard judges

The decision is by what the file, as it now stands, would do to the safety posture, not by its name.

**Blocked**, for a user, project or local settings file:

| The file | Why |
|---|---|
| sets `disableAllHooks` to `true` | every hook, this one included, stops running |
| sets `HOME`, `DAMAGE_CONTROL_HOME` or `DAMAGE_CONTROL_UNATTENDED_ALLOW` in `env` | every hook reads its policy and grants through those; a host profile's own config-home and grant variables count too |
| is a file `init` registered into, and no longer carries the registration `init` wrote | an entry removed, rewritten, re-matched, or stripped of `timeout` or `onFailure`, or the `ConfigChange` entry itself gone |
| is a file `init` registered into, and is deleted, unreadable or not a JSON object | Claude Code could not load the registration from it |

"A file `init` registered into" means the settings path recorded in the install record under the config home. A registration made by a host installer without a record is judged by the first two rows only.

**Allowed**, and audited like any other allowed call: everything else, including a wider `permissions.allow`, a hook that is not ours, an unparseable or deleted file we never registered into, and any change to a skill file.

**Observed**, for a managed-policy file (`policy_settings`): Claude Code applies that change whatever a hook says, so the guard exits 0 and writes an `observed` audit row naming what it would have blocked, or `no finding`.

Every block writes an audit row with `rule_id` `core.config-change`, the file and the reason. The exit-2 message on stderr is for the debug log only.

## What it does not do

- **Widening `permissions.allow` is not blocked.** With no earlier copy there is no "widening" to detect, and an allow rule does not override a hook's block, so it does not switch the guard off.
- **A hook that is not ours is not blocked.** Users and teams register their own; the guard cannot tell a good one from a bad one.
- **It does not undo the file.** A block keeps the change from the running session; the file on disk keeps the bad content and loads next session. `damage-control-dev status` and `doctor` read the file and report it (`config-guard`, `unsafe-setting`, and the drift findings), so run one after a block.
- **It runs as the same user.** A process that can write the settings file can also edit the Python environment the hook runs from; see the [threat model](threat-model.md).
- **`init` rewriting its own registration from a new environment is refused in already-running sessions**: the record still names the old interpreter, so the guard sees drift. The change applies at the next session.

## Registration, status and doctor

`damage-control-dev init` registers one entry under `ConfigChange`, in the same exec form as the tool hooks (`-I` bootstrap, `timeout`, `onFailure: "block"`):

```json
{
  "matcher": "user_settings|project_settings|local_settings|policy_settings",
  "hooks": [{"type": "command", "command": "/path/to/venv/bin/python",
             "args": ["-I", "-m", "damage_control.hook", "config"],
             "timeout": 30, "onFailure": "block"}]
}
```

Skill files are left out of the matcher: they cannot change any of the settings above. Registration is idempotent, a drifted entry is repaired, entries that are not ours are left alone, and `uninstall` removes it.

`status` and `doctor` report `config-guard` (`ok` when registered, `bad` when not, for example in an install that predates it) and an `unsafe-setting` finding for a registered file that disables hooks or redirects the config home. `init`'s self-test runs the hook: it must exit 0 for a skill change and exit 2 for a settings file that sets `disableAllHooks`.

## Why there are no corpus rows

The [conformance corpus](conformance.md) replays shell commands through the `bash` hook: a row is a command, a working directory and a verdict. A settings-change case is a payload naming a file whose contents decide the verdict, run through a different hook kind, so the row format cannot say it. The cases live in `tests/test_config_change.py`, which drives the real `config` hook entrypoint as a subprocess, and in `tests/test_install_config_guard.py` for registration.

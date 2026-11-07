"""Break-glass leaves nothing of ours registered, under any event, and keeps no event list of its own."""

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from damage_control import breakglass
from damage_control import claude_code as cc
from damage_control import install

SCRIPT = Path(breakglass.__file__)
FOREIGN = {"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}


def registered(events=None):
    events = cc.EVENTS if events is None else events
    desired = {event: {m: cc.wanted_hook("/usr/bin/python3", k, 30, True) for m, k in matchers.items()}
               for event, matchers in events.items()}
    settings = {}
    install.register(settings, desired, [])
    return settings


def break_glass(tmp_path, settings, command="unregister", expect=0):
    """Run the script as a human would: a separate stdlib-only interpreter, scratch HOME, scratch settings file."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)}
    done = subprocess.run([sys.executable, "-I", str(SCRIPT), command, "--settings", str(path)],
                          env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == expect, done.stdout + done.stderr
    return json.loads(path.read_text()), done.stdout


def ours_left(settings):
    return [(o.event, o.matcher) for o in cc.owned_entries(settings)]


def test_every_registered_event_is_cleared(tmp_path):
    settings = registered()
    assert {o.event for o in cc.owned_entries(settings)} == set(cc.EVENTS)
    after, _ = break_glass(tmp_path, settings)
    assert ours_left(after) == []
    assert json.dumps(after).count(cc.HOOK_MODULE) == 0


def test_a_new_hook_kind_is_cleared_without_touching_break_glass(tmp_path, monkeypatch):
    events = dict(cc.EVENTS, SomeFutureEvent={"future_source": "future_kind"})
    monkeypatch.setattr(cc, "EVENTS", events)
    settings = registered()
    assert "SomeFutureEvent" in settings["hooks"]
    after, _ = break_glass(tmp_path, settings)
    assert ours_left(after) == []


def test_break_glass_has_no_event_names_of_its_own():
    source = SCRIPT.read_text()
    for event in cc.EVENTS:
        assert event not in re.sub(r'""".*?"""', "", source, flags=re.S), event


def test_foreign_entries_survive_in_every_event(tmp_path):
    settings = registered()
    for event in cc.EVENTS:
        settings["hooks"][event].append(copy.deepcopy(FOREIGN))
    after, _ = break_glass(tmp_path, settings)
    assert ours_left(after) == []
    assert {event: entries for event, entries in after["hooks"].items()} == {e: [FOREIGN] for e in cc.EVENTS}


def test_status_counts_every_event(tmp_path):
    settings = registered()
    _, out = break_glass(tmp_path, settings, "status", expect=1)  # 1: the interpreter is not importable
    assert f"{len(cc.owned_entries(settings))} damage-control hook entries" in out


def test_break_glass_and_the_engine_agree_on_what_is_ours():
    assert breakglass.HOOK_MODULE == cc.HOOK_MODULE
    settings = registered()
    settings["hooks"]["Elsewhere"] = [{"matcher": "x", "hooks": [dict(cc.wanted_hook("/p", "bash", 1, True))]}]
    settings["hooks"]["PreToolUse"].append(copy.deepcopy(FOREIGN))
    assert [(e, m) for e, m, _ in breakglass.owned(settings)] == ours_left(settings)
    assert not breakglass.is_ours(FOREIGN["hooks"][0]) and not cc.is_ours(FOREIGN["hooks"][0])


def test_uninstall_path_clears_every_event_too():
    settings = registered()
    settings["hooks"]["Elsewhere"] = [{"matcher": "x", "hooks": [cc.wanted_hook("/p", "bash", 1, True)]}]
    settings["hooks"]["PreToolUse"].append(copy.deepcopy(FOREIGN))
    assert install.unregister(settings, ["hooks"]) is True
    assert ours_left(settings) == []
    assert settings["hooks"]["PreToolUse"] == [FOREIGN]


def test_register_drops_an_entry_of_ours_under_an_event_it_does_not_register():
    settings = {"hooks": {"Elsewhere": [{"matcher": "x", "hooks": [cc.wanted_hook("/p", "bash", 1, True)]}]}}
    assert install.register(settings, {}, []) is True
    assert ours_left(settings) == []

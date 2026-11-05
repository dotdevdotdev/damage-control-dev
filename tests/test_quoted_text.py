"""A guarded path named in text a command only prints, sends or writes is data, not an operand.

The first table drives the real hook entrypoint as a subprocess over message-text shapes (echo,
printf, messaging commands, heredoc bodies written to a file) that name a zero-access path in
prose; each must be allowed. The second table puts the same path where the command opens it, or
where the text can still become a command's operand or run, and each must still be blocked.
"""

from hookrun import run_hook

PATH = "~/.ssh/id_rsa"

PROSE_ALLOWED = [
    'echo "notes mention ' + PATH + ' and ~/.aws/credentials"',
    "echo 'notes mention " + PATH + "'",
    "printf '%s\\n' 'see " + PATH + "'",
    'echo "see ~/.zshrc and ~/.claude/settings.json"',
    'agentwire notify-parent --queued "done: moved /bin/ and uv.lock, see ' + PATH + '"',
    'agentwire msg send --to x --kind done "read ' + PATH + ' docs"',
    "cat > /tmp/dc-notes.md <<'EOF'\nthe file " + PATH + " is guarded\nEOF",
    "cat <<EOF > /tmp/dc-notes.md\n" + PATH + "\nEOF",
    "cat <<EOF\n" + PATH + "\nEOF",
    "tee /tmp/dc-notes.md <<'EOF'\n" + PATH + "\nEOF",
]

OPERANDS_BLOCKED = [
    'cat "' + PATH + '"',
    "cat '" + PATH + "'",
    'echo "msg" ; cat "' + PATH + '"',
    'echo "' + PATH + '" | xargs cat',
    'echo "x" 2>&1 | xargs cat "' + PATH + '"',
    'cat $(echo "' + PATH + '")',
    'echo "x" > "' + PATH + '"',
    "echo x >> ~/.ssh/authorized_keys",
    'agentwire notify-parent --body-file "' + PATH + '"',
    "agentwire msg send --to x --body-file '" + PATH + "'",
    "cat > ~/.ssh/authorized_keys <<EOF\nkey\nEOF",
    "bash <<'EOF'\ncat " + PATH + "\nEOF",
    "cat <<'EOF' | sh\ncat " + PATH + "\nEOF",
    "python3 - <<'EOF'\nprint(open('" + PATH + "').read())\nEOF",
    "cat <<'EOF' | xargs cat\n" + PATH + "\nEOF",
    'cat `echo "' + PATH + '"`',
    'echo "$(cat ' + PATH + ')"',
    "echo hi; cat <<EOF\n$(cat " + PATH + ")\nEOF",
]


def _verdicts(commands, tmp_path):
    return {c: run_hook("bash", "Bash", {"command": c}, str(tmp_path), tmp_path) for c in commands}


def test_path_named_in_printed_or_sent_text_is_allowed(tmp_path):
    got = _verdicts(PROSE_ALLOWED, tmp_path)
    assert {c: v for c, v in got.items() if v != "allow"} == {}


def test_path_the_command_opens_or_the_text_can_reach_stays_blocked(tmp_path):
    got = _verdicts(OPERANDS_BLOCKED, tmp_path)
    assert {c: v for c, v in got.items() if v != "block"} == {}

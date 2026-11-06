# Contributing

- Sign off every commit (`git commit -s`): the project uses the Developer
  Certificate of Origin, no CLA.
- A rule change must include the rule (in its pack, with an explicit stable
  `id:`), one must-block and one must-allow case, and a rebuilt JSON
  (`python tools/build_rules_json.py src/damage_control/rules src/damage_control/tooldefs`). Rule ids are frozen: a removal or
  rename is a changelog entry, never an alias.
- Do not paste rules or code from projects whose license is incompatible with
  Apache-2.0.
- Scope: macOS and Linux, Claude Code. Other platforms and harnesses are out
  of scope.

## Submitting a corpus row

If you find a respelling the hook judges differently from the plain command, send it as a row for the
conformance corpus (`src/damage_control/corpus_rows.json`, rendered in [docs/conformance.md](docs/conformance.md)).
An issue with the row is enough; a pull request with the row and its fix is better.

A row has the keys `id`, `class`, `command`, `cwd`, `verdict` (`block`, `ask` or `allow`) and `source`
(where the form came from), and optionally `tool` (`Bash` by default, or `PowerShell` or `Monitor`, the tool that carries the command). A row is a respelling of an operation the rules already judge, so give the
verdict the plain command gets, and add a control row (same spelling, harmless command, `allow`) when the
spelling alone must not trigger anything. Use `@HOME@` for the home directory the hook sees and `@ROOT@`
for the scratch tree built from the `files` map.

Then run `damage-control-dev corpus run` and `python tools/conformance_doc.py`. A row that fails
until its fix lands stays out of the corpus: every row in the table passes on `main`.

`damage-control-dev corpus fuzz [--n N] [--seed S]` respells every `block` and `ask` row (quote splits,
backslashes, the field separator variable, `~` / `$HOME` / `${HOME}` / absolute / variable forms of the
home directory, repeated slashes, `.` and `..` segments, brace groups, letter case where the platform folds
it) and lists every respelling whose verdict differs from its row. The same seed gives the same list. Send
a miss as its own issue; the test suite lists the classes with an open issue and excludes only those.

Whoever submits a row that leads to a fix is credited by name (or handle) in the release notes.

See `docs/rule-authoring.md` and `docs/extending.md`.

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

See `docs/rule-authoring.md` and `docs/extending.md`.

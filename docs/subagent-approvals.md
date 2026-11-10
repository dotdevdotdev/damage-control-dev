# Subagents and approvals

A subagent cannot answer an `ask`. A background agent has no prompt to show (Claude Code marks it non-interactive), so with nothing to decide the request the call hangs or is denied later, and a person may only hear about it through a hook of their own. damage-control therefore does not ask on a subagent's behalf.

## What happens

1. A call with an `agent_id` in its hook payload that the rules would `ask` about is blocked at once. The agent's tool result gives the reason, the command, its directory, and an instruction: do not retry or work around it, finish what it can, and end the report with a line starting `NEEDS APPROVAL:` that gives the exact command, its directory and why. The audit row is `blocked`, `blocked_by` starts `subagent cannot ask:`, and it carries the real `agent_id` and `agent_type`.
2. A background agent's report reaches the parent session as a `<task-notification>` prompt, and a workflow's result comes back the same way with each agent's report inside it. The `approval` hook (`UserPromptSubmit`) reads that prompt. If it holds `NEEDS APPROVAL:` lines, it adds an instruction to the parent: run each listed command in the parent session. The parent's own call is judged like any other, and the user sees the guard's normal approval prompt for that exact command. That prompt is the single approval step; the parent is told not to ask in words first. The text is marked untrusted, and if the agent is still needed the parent passes it the result with `SendMessage`. The user also gets a one-line notice.
3. Only the backticked command and directory are quoted back. The rest of the line is the agent's prose and is dropped.

Approval is never passed down to the subagent. The parent runs the command, so the parent's rules and prompt apply.

## Limits

- The `approval` hook reads only a `<task-notification>` prompt. A prompt you type is never touched, even if it contains the words.
- It acts through the parent model. The instruction is delivered to it every time, but it is still an instruction. The user-facing notice does not depend on the model.
- The parent's prompt is the guard's own, so it appears only when the parent's rules ask. A subagent running in a stricter mode than a parent in `bypassPermissions` could be handed an ask that the parent's bypass lifts; the command then runs without a prompt, as any command of that kind would in that session.
- A finished workflow has no agent left to message. The parent runs the approved command and redoes or finishes that step itself.
- The hook runs on every prompt, takes about 20 ms, loads no rules, and fails open: any failure is no output and exit 0, never an exit 2, which would erase the prompt. It is registered without `onFailure: block`.
- Register it by running `damage-control-dev init` again. `status` reports it as `UserPromptSubmit hand-back`.

"""One decision per Claude Code tool: judged by a hook, or out of scope and why.

``docs/coverage.md`` renders this table and a test holds it to ``claude_code.MATCHERS``, so a tool
cannot be registered, or dropped, without a recorded decision. The names are the built-in tools
read in Claude Code 2.1.319 (the strings of its binary and the hook-input schema it validates; the payloads of
``Agent``, ``Bash``, ``Glob`` and ``Monitor`` were also observed live, so the input shapes of the other tools are
read, not exercised) plus the
tools the hooks reference lists. A tool Claude Code adds later is not here until someone reviews it:
add a row with a decision, and the test passes.

Standard library only.
"""

from typing import NamedTuple, Tuple

JUDGED = "judged"
OUT_OF_SCOPE = "out of scope"


class ToolDecision(NamedTuple):
    names: Tuple[str, ...]  # tool names (or the matcher) this decision covers
    harm: str  # what the tool can do that the judged tools cannot, or "nothing beyond ..."
    decision: str  # JUDGED | OUT_OF_SCOPE
    reason: str


def _d(names: str, harm: str, decision: str, reason: str) -> ToolDecision:
    return ToolDecision(tuple(n.strip() for n in names.split(",")), harm, decision, reason)


DECISIONS: Tuple[ToolDecision, ...] = (
    _d("Bash, PowerShell", "runs any command", JUDGED, "the rules judge the command line"),
    _d("Monitor", "runs a command in the background and streams its output", JUDGED,
       "the `command` field is a shell command, judged by the same rules as Bash. A `url` monitor (a WebSocket "
       "opened by Claude Code) has no command and is not judged. From Claude Code 2.1.314 a `Bash` hook also runs "
       "for a Monitor call; the two hook processes share one `tool_use_id`, and only the first to claim it judges "
       "and writes the audit row"),
    _d("Edit, NotebookEdit, Write", "changes any file the user can", JUDGED,
       "the target path is judged, and script-looking text is asked about"),
    _d("Read, Grep, Glob", "reads file contents or lists names", JUDGED, "the path is judged"),
    _d("LSP", "returns symbols, documentation and call sites of the file named in `filePath`", JUDGED,
       "reads a file by path like Read does, so the same path ladder applies"),
    _d("mcp__.*", "whatever the server offers", JUDGED,
       "the tool name and its path-valued arguments are judged; a host profile can map a tool to the command it runs"),
    _d("WebFetch, WebSearch", "sends text out in the URL or the query, and brings page text back", OUT_OF_SCOPE,
       "the engine has no egress policy, for Bash `curl` either, and a URL or query that carries data is "
       "indistinguishable from one that does not. Claude Code refuses private and local hosts for WebFetch "
       "itself, and its permission rules limit domains. Returned text is untrusted input, not an action"),
    _d("Agent, Workflow", "starts a subagent with a prompt of the model's choosing", OUT_OF_SCOPE,
       "the child's own tool calls reach the hooks: the hook input carries `agent_id` and `agent_type` for a call "
       "made inside a subagent (observed live, see the [hooks research](hooks-research.md)). The tool name in the "
       "payload is `Agent` (older versions called it `Task`). The prompt is text, not an action"),
    _d("Skill", "loads the instructions of a named skill into the conversation", OUT_OF_SCOPE,
       "it runs nothing itself; what the instructions then do goes through the judged tools, and the skill "
       "directories are part of the protected control plane"),
    _d("SendMessage, SubagentHandback, SendUserMessage (alias Brief), SendUserFile, PushNotification", "tells the user or another agent something, or attaches a file for the user",
       OUT_OF_SCOPE, "the recipient is the user or an agent in the same session; nothing leaves for a third party"),
    _d("AskUserQuestion, EnterPlanMode, ExitPlanMode", "nothing: they ask the user or switch the permission mode "
       "toward more questions", OUT_OF_SCOPE, "the user decides, and nothing is read or written"),
    _d("TodoWrite, TaskCreate, TaskUpdate, TaskGet, TaskList, TaskStop (alias KillShell, KillBash)",
       "nothing beyond bookkeeping in the session; TaskStop ends a background task", OUT_OF_SCOPE,
       "no file, command or network access"),
    _d("EnterWorktree, ExitWorktree", "creates or leaves a git worktree and changes the working directory",
       OUT_OF_SCOPE, "the commands that follow are judged against the new directory; creating a worktree does not "
       "delete or overwrite anything"),
    _d("CronCreate, CronDelete, CronList, ScheduleWakeup", "queues a prompt to run later", OUT_OF_SCOPE,
       "the prompt is text, and what it does when it runs goes through the judged tools"),
    _d("RemoteTrigger", "manages scheduled remote agents (routines) through the claude.ai API", OUT_OF_SCOPE,
       "it acts on the user's account, not on this machine; the routine is a prompt run elsewhere, outside "
       "these hooks"),
    _d("ToolSearch, ListMcpResourcesTool, ReadMcpResourceTool, ReadMcpResourceDirTool",
       "lists tool schemas, or reads a resource an MCP server exposes by URI", OUT_OF_SCOPE,
       "a URI names a server resource, not a local path; the server is the party to trust or not"),
    _d("REPL (alias Eval)", "evaluates code inside Claude Code", OUT_OF_SCOPE,
       "feature-gated: the name is in the binary, and its input shape was not observed. Revisit when it can be "
       "exercised; until then the claim is only that it was seen, not that it is harmless"),
)

JUDGED_NAMES = tuple(n for d in DECISIONS if d.decision == JUDGED for n in d.names)

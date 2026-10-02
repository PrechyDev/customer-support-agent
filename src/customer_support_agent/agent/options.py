"""SDK settings for one call's agent session. Every value here is a deliberate lock-down (SPECS §8)."""

from pathlib import Path

from collections.abc import Callable

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

from customer_support_agent.config import AgentSettings

MCP_SERVER = "relaypay"
TOOL_NAMES = ("search_knowledge_base", "lookup_customer", "lookup_transaction", "lookup_payout",
              "create_support_ticket", "create_escalation", "log_conversation_event")
ALLOWED_TOOLS = [f"mcp__{MCP_SERVER}__{name}" for name in TOOL_NAMES]


def build_options(settings: AgentSettings, system_prompt: str, conversation_id: str, workdir: Path,
                  stop_hook: Callable | None = None) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=system_prompt,  # replaces Claude Code's own coding-assistant prompt
        model=settings.model,
        max_turns=settings.max_turns,
        tools=[],  # no built-in file, shell or web tools
        allowed_tools=list(ALLOWED_TOOLS),  # our tools run without a permission prompt
        permission_mode="dontAsk",  # anything not allowed is refused, never asked about
        mcp_servers={
            MCP_SERVER: {
                "type": "http",
                "url": settings.mcp_url,
                "headers": {
                    "Authorization": f"Bearer {settings.mcp_auth_token}",
                    "X-Conversation-Id": conversation_id,  # set here, never by the model
                },
            }
        },
        strict_mcp_config=True,  # ignore every other MCP server on the machine
        setting_sources=[],  # don't load ~/.claude settings, hooks, plugins or CLAUDE.md
        include_partial_messages=True,  # text arrives in pieces so Vapi can speak sooner
        thinking={"type": "disabled"},  # thinking adds seconds before the first word
        cwd=str(workdir),  # an empty folder, not the repo
        # Our own code, run when the agent is about to finish a turn (agent/promise_guard.py).
        hooks={"Stop": [HookMatcher(hooks=[stop_hook])]} if stop_hook else None,
        env={
            "ANTHROPIC_API_KEY": settings.anthropic_api_key,
            # Auto memory loads into the prompt even with setting_sources=[] (SDK hosting docs).
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            # The engine's own config and transcripts go here, not the developer's ~/.claude.
            "CLAUDE_CONFIG_DIR": str(workdir / "claude-config"),
        },
    )

"""
Detect the current AI agent environment and output the correct tool name
to use when presenting interactive options to the user.

Usage:
    python3 get_ask_tool.py

Output (one of):
    AskUserQuestion   — Claude Code (terminal / CLI)
    ask_user_input_v0 — Claude.ai web or mobile
    agent_choice      — Unknown / third-party agent (Codex, OpenClaw, etc.)
                        The AI agent should use whatever interactive
                        question tool its environment provides, or fall
                        back to presenting numbered options in plain text.
"""

import os
import shutil


def get_ask_tool() -> str:
    # ── Claude Code ──────────────────────────────────────────────────────
    # Claude Code sets CLAUDE_CODE in the shell environment.
    if os.environ.get("CLAUDE_CODE"):
        return "AskUserQuestion"

    # Claude Code also installs the `claude` CLI binary into PATH.
    if shutil.which("claude"):
        return "AskUserQuestion"

    # ── Claude.ai web / mobile sandbox ───────────────────────────────────
    # Claude.ai's sandbox container mounts /mnt/user-data for file output.
    # This path is specific to Anthropic's hosted environment.
    if os.path.isdir("/mnt/user-data"):
        return "ask_user_input_v0"

    # ── Unknown / third-party agent ──────────────────────────────────────
    # Could be Codex, OpenClaw, a custom agent, or a self-hosted runner.
    # Signal the caller to use whatever question tool is available.
    return "agent_choice"


if __name__ == "__main__":
    print(get_ask_tool())

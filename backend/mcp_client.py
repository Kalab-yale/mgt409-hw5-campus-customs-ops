"""Connects the agent team to the Campus Customs MCP server.

This is the ONLY way agents reach shop data: there is no direct database
access in the backend. Each MCP call passes through `_process_tool_call`,
which stamps the calling agent onto write requests and writes an audit record.
"""

from __future__ import annotations

import sys
import time
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from pydantic_ai import RunContext
from pydantic_ai.mcp import CallToolFunc, MCPToolset
from pydantic_ai.toolsets import AbstractToolset

from config import MCP_SERVER_SCRIPT, PROJECT_DIR
from models import AgentDeps, RoleSpec

# MCP tool argument -> filled in by the backend with the running agent's name,
# so a model can't claim to be a different agent to get more permissions.
IDENTITY_ARGS = {"request_approval": "requested_by", "update_ticket_status": "updated_by"}

# Tools only the dashboard backend may call, after a human clicks a button.
# No role lists them, and the hook below refuses them even if one slipped through.
HUMAN_ONLY_TOOLS = frozenset({"approve_request", "reject_request", "resolve_ticket", "reset_database"})


async def _process_tool_call(
    ctx: RunContext[AgentDeps], call_tool: CallToolFunc, name: str, args: dict[str, Any]
) -> Any:
    deps = ctx.deps
    if name in HUMAN_ONLY_TOOLS:
        await deps.audit.append(
            "guardrail_block", run_id=deps.run_id, agent_run_id=deps.agent_run_id, ticket_id=deps.ticket_id,
            agent=deps.agent, tool=name, args=args, reason="human-only tool",
        )
        return {"ok": False, "message": f"{name} is human-only. Agents prepare requests; a person approves them."}
    if name in IDENTITY_ARGS:
        args = {**args, IDENTITY_ARGS[name]: deps.agent}

    started = time.perf_counter()
    try:
        result = await call_tool(name, args)
    except Exception as exc:
        await deps.audit.append(
            "mcp_tool_error",
            run_id=deps.run_id, agent_run_id=deps.agent_run_id, ticket_id=deps.ticket_id,
            agent=deps.agent, depth=deps.depth, tool=name, args=args, error=repr(exc),
        )
        raise
    await deps.audit.append(
        "mcp_tool_result",
        run_id=deps.run_id, agent_run_id=deps.agent_run_id, ticket_id=deps.ticket_id,
        agent=deps.agent, depth=deps.depth, tool=name, args=args, result=result,
        ms=round((time.perf_counter() - started) * 1000),
    )
    return result


def build_mcp_toolset() -> MCPToolset:
    """One stdio connection to mcp_server/server.py, shared by all five agents."""
    transport = StdioTransport(
        command=sys.executable, args=[str(MCP_SERVER_SCRIPT)], cwd=str(PROJECT_DIR)
    )
    return MCPToolset(Client(transport), process_tool_call=_process_tool_call, max_retries=1)


def toolset_for_role(toolset: MCPToolset, role: RoleSpec) -> AbstractToolset[AgentDeps]:
    """Each agent only sees the MCP tools its role needs."""
    assert not role.mcp_tools & HUMAN_ONLY_TOOLS, f"{role.name} must not get human-only tools"
    return toolset.filtered(lambda ctx, tool_def: tool_def.name in role.mcp_tools)

"""The Campus Customs agent team: five PydanticAI agents, fully connected.

- Every agent gets its role's MCP tools plus one `delegate` tool that can
  hand work to ANY other agent (full mesh). Guardrails stop self-delegation,
  loops, runaway depth, and too many hand-offs per ticket.
- Every agent run is driven step by step with `agent.iter()`, and each step
  (prompt, model request, model response, final output) is appended to
  output/audit_trail.json, along with every MCP call and delegation.

Usage:
    async with Team() as team:
        decision = await team.handle_ticket(101)
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    RetryPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage

from agents import ROLES
from audit import AuditLog
from config import (
    MAX_DELEGATION_DEPTH,
    MAX_DELEGATIONS_PER_TICKET,
    MAX_OUTPUT_TOKENS_PER_CALL,
    MODEL_NAME,
    PORTKEY_BASE_URL,
    PROMPTS_DIR,
    TICKET_USAGE_LIMITS,
)
from mcp_client import build_mcp_toolset, toolset_for_role
from models import AGENT_NAMES, AgentDeps, AgentName, RoleSpec, RunBudget, TicketDecision


def build_model() -> OpenAIChatModel:
    """gpt-6-luna through Portkey. The key is read from the environment, never printed."""
    api_key = os.environ.get("PORTKEY_API_KEY")
    if not api_key:
        raise RuntimeError("PORTKEY_API_KEY is not set. Add it to .env (see .env.example).")
    client = AsyncOpenAI(
        api_key=api_key, base_url=PORTKEY_BASE_URL, default_headers={"x-portkey-provider": "openai"}
    )
    return OpenAIChatModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


def load_prompt(role: RoleSpec) -> str:
    shared = (PROMPTS_DIR / "_shared.md").read_text(encoding="utf-8")
    own = (PROMPTS_DIR / role.prompt_file).read_text(encoding="utf-8")
    return f"{shared}\n\n{own}"


def run_context_instructions(ctx: RunContext[AgentDeps]) -> str:
    """Per-run facts each agent sees: who it is, the ticket, and its delegation budget."""
    d = ctx.deps
    return (
        f"You are the **{d.agent}** agent. Ticket: {d.ticket_id if d.ticket_id is not None else 'none'}.\n"
        f"Delegation chain so far: {' -> '.join(d.chain)} (depth {d.depth}/{MAX_DELEGATION_DEPTH}). "
        f"Delegations left for this ticket: {MAX_DELEGATIONS_PER_TICKET - d.budget.delegations_used}."
    )


def _delegate_description() -> str:
    roster = "\n".join(f"- {r.name}: {r.description}" for r in ROLES.values())
    return (
        "Hand a task to another Campus Customs agent and get their report back.\n"
        f"Agents:\n{roster}\n"
        "Write `task` so it stands alone: include the ticket id and any facts you already have."
    )


def _summarize_parts(parts: Any) -> list[dict]:
    """Turn message parts into small, readable audit entries."""
    out: list[dict] = []
    for p in parts:
        if isinstance(p, ToolCallPart):
            out.append({"type": "tool_call", "tool": p.tool_name, "tool_call_id": p.tool_call_id, "args": p.args_as_dict()})
        elif isinstance(p, ToolReturnPart):
            out.append({"type": "tool_return", "tool": p.tool_name, "tool_call_id": p.tool_call_id, "content": p.model_response_str()})
        elif isinstance(p, RetryPromptPart):
            out.append({"type": "retry", "tool": p.tool_name, "content": p.model_response()})
        elif isinstance(p, TextPart):
            out.append({"type": "text", "content": p.content})
        elif isinstance(p, UserPromptPart):
            out.append({"type": "user_prompt", "content": p.content if isinstance(p.content, str) else str(p.content)})
        elif isinstance(p, ThinkingPart):
            out.append({"type": "thinking", "chars": len(p.content or "")})
        else:
            out.append({"type": type(p).__name__})
    return out


def _usage_dict(u: RunUsage) -> dict:
    return {"requests": u.requests, "tool_calls": u.tool_calls, "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens, "total_tokens": u.total_tokens}


class Team:
    """Holds the MCP connection, the five agents, and the audit log."""

    def __init__(self, audit: AuditLog | None = None) -> None:
        self.audit = audit or AuditLog()
        self.mcp = build_mcp_toolset()
        model = build_model()
        delegate_tool = Tool(self._delegate, name="delegate", description=_delegate_description(), takes_ctx=True)
        self.agents: dict[AgentName, Agent[AgentDeps, Any]] = {
            role.name: Agent(
                model,
                name=role.name,
                deps_type=AgentDeps,
                output_type=role.output_type,
                instructions=[load_prompt(role), run_context_instructions],
                toolsets=[toolset_for_role(self.mcp, role)],
                tools=[delegate_tool],
                model_settings=OpenAIChatModelSettings(
                    max_tokens=MAX_OUTPUT_TOKENS_PER_CALL,
                    # gpt-6-luna only allows function tools on chat completions with reasoning off.
                    openai_reasoning_effort="none",
                ),
                retries=2,
            )
            for role in ROLES.values()
        }

    async def __aenter__(self) -> Team:
        await self.mcp.__aenter__()  # start the MCP server once for the whole team
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.mcp.__aexit__(*exc)

    # ---------------------------------------------------------------- entry point

    async def handle_ticket(self, ticket_id: int, run_id: str | None = None) -> TicketDecision | None:
        """Give one ticket to the Boss and let the team work it. Returns the Boss's decision."""
        run_id = run_id or uuid.uuid4().hex[:12]
        deps = AgentDeps(
            agent="boss", ticket_id=ticket_id, run_id=run_id, agent_run_id=uuid.uuid4().hex[:12],
            audit=self.audit, budget=RunBudget(), depth=0, chain=("boss",),
        )
        usage = RunUsage()
        await self.audit.append("ticket_run_start", run_id=run_id, ticket_id=ticket_id, model=MODEL_NAME,
                                limits={"request_limit": TICKET_USAGE_LIMITS.request_limit,
                                        "tool_calls_limit": TICKET_USAGE_LIMITS.tool_calls_limit,
                                        "total_tokens_limit": TICKET_USAGE_LIMITS.total_tokens_limit,
                                        "max_delegation_depth": MAX_DELEGATION_DEPTH,
                                        "max_delegations": MAX_DELEGATIONS_PER_TICKET})
        try:
            decision = await self.run_agent(
                "boss",
                f"Handle ticket {ticket_id}. Work it with the team and return your final decision.",
                deps, usage,
            )
        except UsageLimitExceeded as exc:
            await self.audit.append("ticket_run_aborted", run_id=run_id, ticket_id=ticket_id,
                                    reason=f"usage limit: {exc}", usage=_usage_dict(usage))
            return None
        except Exception as exc:
            await self.audit.append("ticket_run_error", run_id=run_id, ticket_id=ticket_id,
                                    error=repr(exc), usage=_usage_dict(usage))
            raise
        await self.audit.append("ticket_run_end", run_id=run_id, ticket_id=ticket_id,
                                decision=decision.model_dump(), usage=_usage_dict(usage),
                                delegations=deps.budget.delegations_used)
        return decision

    # ---------------------------------------------------------------- the agent loop

    async def run_agent(self, name: AgentName, task: str, deps: AgentDeps, usage: RunUsage) -> Any:
        """Run one agent step by step, auditing every node of its loop."""
        agent = self.agents[name]
        base = {"run_id": deps.run_id, "agent_run_id": deps.agent_run_id, "ticket_id": deps.ticket_id,
                "agent": name, "parent_agent": deps.parent, "depth": deps.depth, "chain": list(deps.chain)}
        try:
            return await self._iterate(agent, task, deps, usage, base)
        except Exception as exc:
            await self.audit.append("agent_error", **base, error=repr(exc), ticket_usage_so_far=_usage_dict(usage))
            raise

    async def _iterate(self, agent: Agent[AgentDeps, Any], task: str, deps: AgentDeps,
                       usage: RunUsage, base: dict) -> Any:
        step = 0
        async with agent.iter(task, deps=deps, usage=usage, usage_limits=TICKET_USAGE_LIMITS) as run:
            async for node in run:
                step += 1
                if Agent.is_user_prompt_node(node):
                    await self.audit.append("agent_step", **base, step=step, node="user_prompt",
                                            prompt=node.user_prompt)
                elif Agent.is_model_request_node(node):
                    await self.audit.append("agent_step", **base, step=step, node="model_request",
                                            parts=_summarize_parts(node.request.parts))
                elif Agent.is_call_tools_node(node):
                    resp = node.model_response
                    await self.audit.append("agent_step", **base, step=step, node="model_response",
                                            model=resp.model_name, parts=_summarize_parts(resp.parts),
                                            response_usage={"input_tokens": resp.usage.input_tokens,
                                                            "output_tokens": resp.usage.output_tokens},
                                            ticket_usage_so_far=_usage_dict(usage))
                elif Agent.is_end_node(node):
                    await self.audit.append("agent_step", **base, step=step, node="end",
                                            output=node.data.output.model_dump())
            return run.result.output

    # ---------------------------------------------------------------- delegation (full mesh)

    async def _delegate(self, ctx: RunContext[AgentDeps], to_agent: AgentName, task: str) -> dict:
        """Hand `task` to `to_agent` and return its report."""
        d = ctx.deps
        refusal = None
        if to_agent not in AGENT_NAMES:
            refusal = f"Unknown agent '{to_agent}'. Choose one of {list(AGENT_NAMES)}."
        elif to_agent == d.agent:
            refusal = "You can't delegate to yourself; do the task with your own tools."
        elif to_agent in d.chain:
            refusal = (f"{to_agent} is already waiting on this chain ({' -> '.join(d.chain)}). "
                       "Report back to it instead of calling it again.")
        elif d.depth >= MAX_DELEGATION_DEPTH:
            refusal = f"Max delegation depth ({MAX_DELEGATION_DEPTH}) reached. Finish with what you have."
        elif d.budget.delegations_used >= MAX_DELEGATIONS_PER_TICKET:
            refusal = f"This ticket used all {MAX_DELEGATIONS_PER_TICKET} delegations. Finish with what you have."

        base = {"run_id": d.run_id, "ticket_id": d.ticket_id, "from_agent": d.agent, "to_agent": to_agent,
                "depth": d.depth, "chain": list(d.chain), "task": task}
        if refusal:
            await self.audit.append("delegation_refused", **base, reason=refusal)
            return {"ok": False, "error": refusal}

        d.budget.delegations_used += 1
        child = AgentDeps(
            agent=to_agent, ticket_id=d.ticket_id, run_id=d.run_id, agent_run_id=uuid.uuid4().hex[:12],
            audit=d.audit, budget=d.budget, depth=d.depth + 1, chain=(*d.chain, to_agent),
        )
        await self.audit.append("delegation_start", **base, child_agent_run_id=child.agent_run_id,
                                delegation_number=d.budget.delegations_used)
        try:
            report = await self.run_agent(to_agent, task, child, ctx.usage)
        except UsageLimitExceeded:
            raise  # the whole ticket stops; handled in handle_ticket
        except Exception as exc:  # one teammate failing shouldn't crash the ticket
            await self.audit.append("delegation_error", **base, child_agent_run_id=child.agent_run_id, error=repr(exc))
            return {"ok": False, "error": f"{to_agent} failed: {exc!r}"}
        await self.audit.append("delegation_end", **base, child_agent_run_id=child.agent_run_id,
                                report=report.model_dump())
        return {"ok": True, "from": to_agent, "report": report.model_dump()}

"""Data types shared by the Campus Customs agent team."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, get_args

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from audit import AuditLog

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
AGENT_NAMES: tuple[AgentName, ...] = get_args(AgentName)


# ---- Structured outputs -----------------------------------------------------

class AgentReport(BaseModel):
    """What a specialist (Inventory, Accounting, Facilities, Customer Service) hands back."""

    agent: AgentName
    summary: str = Field(description="Two to four sentences: what you found and did.")
    facts: list[str] = Field(
        default_factory=list,
        description="Key facts you relied on, each ending with its source tool, e.g. 'S tee qty 0 (check_stock)'.",
    )
    approval_request_ids: list[int] = Field(
        default_factory=list, description="IDs of approval requests you filed or found pending."
    )
    blockers: list[str] = Field(default_factory=list, description="Anything stopping the work.")
    needs_human: bool = Field(description="True if a human must approve or decide something.")


class TicketDecision(BaseModel):
    """The Boss agent's final call on one ticket."""

    ticket_id: int
    decision: Literal["awaiting_approval", "blocked", "in_progress", "no_action_needed"]
    summary: str = Field(description="Plain-English summary for the human manager.")
    plan: list[str] = Field(default_factory=list, description="Ordered next steps, including what the human must approve.")
    approval_request_ids: list[int] = Field(default_factory=list, description="Pending approval requests for this ticket.")
    agents_consulted: list[AgentName] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list, description="Cash conflicts, delays, or anything the human should watch.")


# ---- Roles ------------------------------------------------------------------

@dataclass(frozen=True)
class RoleSpec:
    """Everything that makes an agent one of the five roles."""

    name: AgentName
    title: str
    description: str  # one line, shown to other agents in the delegate tool
    prompt_file: str  # file in backend/prompts/
    mcp_tools: frozenset[str]  # MCP tools this role may call (least privilege)
    output_type: type[BaseModel]


# ---- Run-time context passed to every agent ---------------------------------

@dataclass
class RunBudget:
    """Shared by every agent working on the same ticket."""

    delegations_used: int = 0


@dataclass
class AgentDeps:
    """Who is running, on which ticket, and where in the delegation chain."""

    agent: AgentName
    ticket_id: int | None
    run_id: str  # one per ticket run
    agent_run_id: str  # one per agent invocation
    audit: AuditLog
    budget: RunBudget
    depth: int = 0
    chain: tuple[AgentName, ...] = field(default_factory=tuple)  # e.g. ("boss", "accounting")

    @property
    def parent(self) -> AgentName | None:
        return self.chain[-2] if len(self.chain) >= 2 else None


# ---- API request bodies (backend/main.py) -----------------------------------

class RunTicketRequest(BaseModel):
    ticket_id: int = Field(description="Ticket to hand to the agent team, e.g. 101.")


class ApproveBody(BaseModel):
    approved_by: str = Field(default="manager", min_length=1, max_length=60,
                             description="Name of the human approving (not an agent).")


class RejectBody(BaseModel):
    decided_by: str = Field(default="manager", min_length=1, max_length=60)
    reason: str = Field(default="", max_length=500)


class ResetBody(BaseModel):
    confirm: str = Field(description='Must be exactly "RESET".')

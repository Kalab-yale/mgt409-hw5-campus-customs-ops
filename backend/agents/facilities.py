"""Facilities: the shop space, leases, and rent."""

from models import AgentReport, RoleSpec

ROLE = RoleSpec(
    name="facilities",
    title="Facilities",
    description="Handles the shop space: verifies leases and rent notices against the lease on file.",
    prompt_file="facilities.md",
    mcp_tools=frozenset({"get_ticket", "get_lease", "list_approval_requests"}),
    output_type=AgentReport,
)

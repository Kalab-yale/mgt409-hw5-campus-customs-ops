"""Customer Service: drafts customer messages for human approval."""

from models import AgentReport, RoleSpec

ROLE = RoleSpec(
    name="customer_service",
    title="Customer Service",
    description="Drafts honest, friendly messages to customers and files them for human approval before sending.",
    prompt_file="customer_service.md",
    mcp_tools=frozenset({"get_ticket", "check_stock", "list_approval_requests", "request_approval"}),
    output_type=AgentReport,
)

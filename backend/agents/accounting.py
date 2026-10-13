"""Accounting: cash, invoices, margins; prepares payments and POs for human approval."""

from models import AgentReport, RoleSpec

ROLE = RoleSpec(
    name="accounting",
    title="Accounting",
    description="Tracks cash and invoices, checks margins and discount floors, and files payment / purchase-order / price-quote requests for human approval.",
    prompt_file="accounting.md",
    mcp_tools=frozenset({
        "get_ticket", "get_pricing", "get_invoice", "get_lease", "get_cash_position",
        "list_vendors", "list_approval_requests", "request_approval",
    }),
    output_type=AgentReport,
)

"""Inventory: checks stock by SKU and size, finds shortages and restock vendors."""

from models import AgentReport, RoleSpec

ROLE = RoleSpec(
    name="inventory",
    title="Inventory",
    description="Checks stock by SKU and size, works out shortages, and finds vendors (and lead times) to restock.",
    prompt_file="inventory.md",
    mcp_tools=frozenset({"get_ticket", "check_stock", "list_vendors"}),
    output_type=AgentReport,
)

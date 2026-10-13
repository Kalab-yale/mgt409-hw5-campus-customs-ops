"""Paths, model, and the limits that keep the agent team safe and cheap."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai.usage import UsageLimits

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent  # Homework 5/
PROMPTS_DIR = BACKEND_DIR / "prompts"
MCP_SERVER_SCRIPT = PROJECT_DIR / "mcp_server" / "server.py"
AUDIT_PATH = PROJECT_DIR / "output" / "audit_trail.json"

# Look for .env in Homework 5/ first, then the course folder (where PORTKEY_API_KEY lives).
for env_path in (PROJECT_DIR / ".env", PROJECT_DIR.parents[1] / ".env"):
    load_dotenv(env_path)
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

# One model for every agent.
MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"

# ---- Token / cost limits ----------------------------------------------------
MAX_OUTPUT_TOKENS_PER_CALL = 2500  # cap on any single model response
# Shared by the whole team on one ticket (Boss + everyone it delegates to).
TICKET_USAGE_LIMITS = UsageLimits(
    request_limit=30,  # model calls
    tool_calls_limit=40,  # MCP + delegate calls
    total_tokens_limit=150_000,
)

# ---- Delegation limits ------------------------------------------------------
MAX_DELEGATION_DEPTH = 3  # Boss (0) -> A (1) -> B (2) -> C (3), no deeper
MAX_DELEGATIONS_PER_TICKET = 8

# ---- Audit ------------------------------------------------------------------
AUDIT_TEXT_LIMIT = 2000  # long strings in audit records are cut to this many chars

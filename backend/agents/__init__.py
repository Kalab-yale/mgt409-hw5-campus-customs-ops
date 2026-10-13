"""The five Campus Customs roles. Each file defines one RoleSpec."""

from agents.accounting import ROLE as ACCOUNTING
from agents.boss import ROLE as BOSS
from agents.customer_service import ROLE as CUSTOMER_SERVICE
from agents.facilities import ROLE as FACILITIES
from agents.inventory import ROLE as INVENTORY

ROLES = {role.name: role for role in (BOSS, INVENTORY, ACCOUNTING, FACILITIES, CUSTOMER_SERVICE)}

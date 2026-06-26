"""Agent Least-Privilege Analyzer (alp).

Reads what an AI agent was *granted* (its Entra agent-identity RBAC role
assignments) and what it *actually did* (tool/resource calls from Microsoft
Foundry traces in Application Insights), diffs them, and emits a right-sized,
least-privilege RBAC recommendation.

The core analysis (diff + recommend) is pure and runs offline on sample JSON.
The Azure-backed collectors (granted/used) are thin adapters swapped in for a
live run.
"""

__version__ = "0.1.0"

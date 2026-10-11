"""Run the crew against any AgentHub instance from the command line:

    python -m agents.research_crew "Prepare a customer brief for Acme Corp" \\
        --url http://localhost:8000 --key ah_demo_research_crew_key
"""

import argparse
import asyncio
import json
import uuid

from agents.research_crew.crew import ResearchCrew
from agents.research_crew.gateway_client import GatewayClient


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Research Crew through AgentHub")
    parser.add_argument("task")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--key", default="ah_demo_research_crew_key")
    args = parser.parse_args()

    async def show(event: dict) -> None:
        detail = {k: v for k, v in event.items() if k != "type"}
        print(f"[{event['type']}] {json.dumps(detail, default=str)[:160]}")

    run_id = uuid.uuid4().hex
    gateway = GatewayClient(args.url, args.key, run_id)
    try:
        result = await ResearchCrew(gateway, show, root_span=f"cli-{run_id}").run(args.task)
    finally:
        await gateway.aclose()
    print("\n" + result.get("draft", "") + "\n\nReview: " + result.get("review", ""))


if __name__ == "__main__":
    asyncio.run(main())

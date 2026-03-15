"""Entry point for the campaign pipeline."""

import argparse
import asyncio
import logging
import sys

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from campaign_agent.agent import CampaignPipelineAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

APP_NAME = "campaign_pipeline"
USER_ID = "system"


async def run_pipeline(service_name: str | None = None):
    """Run the campaign pipeline."""
    # Create agent
    agent = CampaignPipelineAgent(
        name="campaign_pipeline",
        description="Campaign page collection and classification pipeline",
        service_name=service_name,
    )

    # Set up ADK runner
    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    # Create session
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
    )

    # Run pipeline
    logger.info("Starting campaign pipeline...")
    if service_name:
        logger.info("Target service: %s", service_name)
    else:
        logger.info("Processing all payment methods")

    message = genai_types.Content(
        parts=[
            genai_types.Part(
                text=f"Process campaigns for: {service_name or 'all services'}"
            )
        ]
    )

    final_event = None
    async for event in runner.run_async(
        session_id=session.id,
        user_id=USER_ID,
        new_message=message,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    logger.info("Agent output: %s", part.text)
        final_event = event

    logger.info("Pipeline completed.")
    return final_event


def main():
    parser = argparse.ArgumentParser(description="Campaign collection pipeline")
    parser.add_argument(
        "--service",
        type=str,
        default=None,
        help="Target service name (e.g., 'PayPay'). If not specified, all services are processed.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_pipeline(args.service))
    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user.")
        sys.exit(0)
    except Exception as e:
        logger.error("Pipeline failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

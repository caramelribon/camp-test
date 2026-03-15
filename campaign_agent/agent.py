"""Root CustomAgent - Orchestrates the campaign pipeline."""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types as genai_types
from google import genai

from campaign_agent.config import MODEL_ID, VALIDATOR_MODEL_ID, GOOGLE_API_KEY, MAX_RETRIES
from campaign_agent.retry import retry_async
from campaign_agent.db import (
    get_payment_methods,
    get_campaigns,
    get_existing_campaign_urls,
    hide_unseen_campaigns,
    create_execution_run,
    update_execution_run,
)
from campaign_agent.tools.seed_collector import collect_seed_urls_async
from campaign_agent.tools.fetch_extract import fetch_and_extract_async
from campaign_agent.tools.browser import close_browser
from campaign_agent.tools.rule_classifier import classify_page
from campaign_agent.agents.llm_page_classifier import (
    LLM_PAGE_CLASSIFIER_INSTRUCTION,
    build_llm_classifier_prompt,
)
from campaign_agent.agents.detail_normalization import (
    DETAIL_NORMALIZATION_INSTRUCTION,
    build_detail_normalization_prompt,
)
from campaign_agent.agents.detail_validator import (
    DETAIL_VALIDATION_INSTRUCTION,
    build_detail_validation_prompt,
)
from campaign_agent.agents.persistence import (
    save_campaign_to_db,
    save_crawl_log_to_db,
)

logger = logging.getLogger(__name__)


def _parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response text."""
    text = text.strip()
    # Try to find JSON block in markdown code fence
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()
    return json.loads(text)


class CampaignPipelineAgent(BaseAgent):
    """Root agent that orchestrates the campaign collection pipeline."""

    model: str = MODEL_ID
    service_name: str | None = None

    model_config = {"arbitrary_types_allowed": True}

    async def _call_llm(self, system_instruction: str, user_prompt: str) -> str:
        """Call Gemini LLM directly with retry (max 3 attempts)."""
        async def _invoke():
            client = genai.Client(api_key=GOOGLE_API_KEY)
            response = await client.aio.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                ),
            )
            return response.text

        return await retry_async(_invoke)

    async def _classify_with_llm(self, features: dict, classification: dict) -> dict:
        """Use LLM to classify an uncertain page."""
        prompt = build_llm_classifier_prompt(features, classification)
        try:
            response_text = await self._call_llm(
                LLM_PAGE_CLASSIFIER_INSTRUCTION, prompt
            )
            result = _parse_json_response(response_text)
            return {
                "label": result.get("label", "not_campaign"),
                "scores": classification.get("scores", {}),
                "is_detail_saveable": result.get("label") == "campaign_detail",
                "used_llm": True,
                "confidence_type": "llm_resolved",
                "reason": result.get("reason", "LLM classification"),
            }
        except Exception as e:
            logger.error("LLM classification failed: %s", e)
            return {
                "label": "not_campaign",
                "scores": classification.get("scores", {}),
                "is_detail_saveable": False,
                "used_llm": True,
                "confidence_type": "llm_error",
                "reason": f"LLM classification error: {e}",
            }

    async def _normalize_detail(
        self, features: dict, service_name: str, source_list_url: str
    ) -> dict:
        """Use LLM to extract campaign data from a detail page."""
        prompt = build_detail_normalization_prompt(
            features, service_name, source_list_url
        )
        try:
            response_text = await self._call_llm(
                DETAIL_NORMALIZATION_INSTRUCTION, prompt
            )
            return _parse_json_response(response_text)
        except Exception as e:
            logger.error("Detail normalization failed: %s", e)
            return {
                "title": features.get("title", features.get("h1", "")),
                "period_text": None,
                "reward_rate_text": None,
                "entry_required": None,
            }

    async def _call_validator_llm(self, system_instruction: str, user_prompt: str) -> str:
        """Call Gemini LLM with the validator model with retry (max 3 attempts)."""
        async def _invoke():
            client = genai.Client(api_key=GOOGLE_API_KEY)
            response = await client.aio.models.generate_content(
                model=VALIDATOR_MODEL_ID,
                contents=user_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                ),
            )
            return response.text

        return await retry_async(_invoke)

    async def _validate_normalized_data(self, features: dict, normalized_data: dict) -> dict:
        """Validate normalized data against original page using a separate LLM.

        Returns:
            dict with 'is_valid' (bool or None) and 'reason' (str).
        """
        prompt = build_detail_validation_prompt(features, normalized_data)
        try:
            response_text = await self._call_validator_llm(
                DETAIL_VALIDATION_INSTRUCTION, prompt
            )
            result = _parse_json_response(response_text)
            is_valid = result.get("is_valid", False)
            summary = result.get("summary", "")
            field_results = result.get("field_results", {})
            reason_parts = [summary]
            for field, fr in field_results.items():
                if not fr.get("valid"):
                    reason_parts.append(f"{field}: {fr.get('reason', 'invalid')}")
            return {"is_valid": is_valid, "reason": "; ".join(reason_parts)}
        except Exception as e:
            logger.error("Validation LLM failed: %s", e)
            return {"is_valid": None, "reason": f"Validation error: {e}"}

    async def _process_url(
        self,
        url: str,
        service_name: str,
        source_list_url: str,
        execution_id: str,
        point_id: int = None,
    ) -> dict:
        """Process a single URL through the pipeline."""
        result = {"url": url, "label": None, "saved": False, "error": None}

        # Step 1: Fetch and extract features
        logger.info("Fetching: %s", url)
        features = await fetch_and_extract_async(url)
        if features.get("error"):
            result["error"] = features["error"]
            result["label"] = "not_campaign"
            save_crawl_log_to_db(
                execution_id,
                url,
                {"label": "not_campaign", "scores": {}, "confidence_type": "fetch_error", "reason": features["error"]},
                error_message=features["error"],
            )
            return result

        # Step 2: Rule-based classification
        classification = classify_page(features)
        logger.info(
            "Classification for %s: %s (scores: %s)",
            url,
            classification["label"],
            classification["scores"],
        )

        # Step 3: If uncertain, use LLM
        if classification["label"] == "uncertain":
            logger.info("Uncertain page, calling LLM: %s", url)
            classification = await self._classify_with_llm(features, classification)
            logger.info("LLM result for %s: %s", url, classification["label"])

        result["label"] = classification["label"]

        # Step 4: If campaign_detail, normalize and save
        campaign_id = None
        if classification["label"] == "campaign_detail":
            # Normalize
            normalized = await self._normalize_detail(
                features, service_name, source_list_url
            )
            # Skip campaigns without reward_rate_text
            if not normalized.get("reward_rate_text"):
                logger.info("Skipped (no reward_rate_text): %s", url)
            else:
                # Validate normalized data against original page
                validation = await self._validate_normalized_data(features, normalized)
                result["validation"] = validation
                if validation["is_valid"] is True:
                    normalized["is_validated"] = True
                    logger.info("Validation passed: %s", url)
                elif validation["is_valid"] is False:
                    normalized["is_validated"] = False
                    logger.warning(
                        "Validation failed: %s — %s", url, validation["reason"]
                    )
                else:
                    # Validation error — save as NULL (unverifiable)
                    normalized["is_validated"] = None
                    logger.warning(
                        "Validation inconclusive: %s — %s", url, validation["reason"]
                    )

                # Save (regardless of validation result)
                save_result = save_campaign_to_db(
                    point_id=point_id,
                    detail_url=url,
                    source_list_url=source_list_url,
                    normalized_data=normalized,
                )
                if save_result["success"]:
                    campaign_id = save_result["campaign_id"]
                    result["saved"] = True
                    logger.info("Saved campaign: %s", url)
                else:
                    result["error"] = save_result.get("error")

        # Step 5: Save crawl log
        save_crawl_log_to_db(
            execution_id, url, classification, campaign_id=campaign_id
        )

        return result

    def _export_campaigns_json(self, service_name: str | None = None) -> str:
        """Export campaigns from DB to a JSON file in campaigns_json/."""
        campaigns = get_campaigns(service_name)
        out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "campaigns_json")
        os.makedirs(out_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{service_name}" if service_name else "_all"
        filename = f"campaigns{suffix}_{timestamp}.json"
        filepath = os.path.join(out_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(campaigns, f, ensure_ascii=False, indent=2, default=str)

        logger.info("Exported %d campaigns to %s", len(campaigns), filepath)
        return filepath

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """Main pipeline orchestration."""
        # Determine which payment methods to process
        target_service = self.service_name or ctx.session.state.get("service_name")
        payment_methods = get_payment_methods(target_service)

        if not payment_methods:
            yield Event(
                author=self.name,
                content=genai_types.Content(
                    parts=[
                        genai_types.Part(
                            text="No payment methods found with campaign URLs."
                        )
                    ]
                ),
            )
            return

        all_results = []
        total_hidden = 0

        try:
            for pm in payment_methods:
                service_name = pm["name"]
                point_id = pm["point_id"]
                seed_url = pm["campaign_list_url"]
                execution_id = str(uuid.uuid4())

                logger.info(
                    "Processing service: %s, seed: %s", service_name, seed_url
                )

                # Fetch existing campaign URLs before processing
                existing_urls = get_existing_campaign_urls(point_id)
                logger.info(
                    "Found %d existing campaigns for %s",
                    len(existing_urls),
                    service_name,
                )
                seen_urls: set[str] = set()

                # Create execution run
                create_execution_run(execution_id, service_name, [seed_url])

                # Collect seed URLs
                seed_result = await collect_seed_urls_async(seed_url)
                if seed_result.get("error"):
                    logger.error(
                        "Seed collection failed for %s: %s",
                        seed_url,
                        seed_result["error"],
                    )
                    update_execution_run(
                        execution_id, status="failed", errors=1
                    )
                    continue

                urls = seed_result["urls"]
                total_urls = len(urls)
                logger.info("Found %d candidate URLs for %s", total_urls, service_name)

                update_execution_run(execution_id, total_urls=total_urls)

                # Process URLs in parallel (max 5 concurrent)
                semaphore = asyncio.Semaphore(5)

                async def _process_with_semaphore(u: str) -> dict:
                    async with semaphore:
                        try:
                            return await self._process_url(
                                u, service_name, seed_url, execution_id, point_id
                            )
                        except Exception as e:
                            logger.error("Error processing %s: %s", u, e)
                            return {"url": u, "label": None, "saved": False, "error": str(e)}

                url_results = await asyncio.gather(
                    *[_process_with_semaphore(u) for u in urls]
                )

                # Track seen URLs (only campaign_detail pages)
                for r in url_results:
                    if r.get("label") == "campaign_detail":
                        seen_urls.add(r["url"])

                processed = len(url_results)
                saved = sum(1 for r in url_results if r.get("saved"))
                errors = sum(1 for r in url_results if r.get("error"))
                all_results.extend(url_results)

                update_execution_run(
                    execution_id,
                    processed_urls=processed,
                    saved_campaigns=saved,
                    errors=errors,
                )

                # Hide campaigns that were not found in this run
                try:
                    hidden = hide_unseen_campaigns(point_id, seen_urls)
                    total_hidden += hidden
                    logger.info(
                        "Hidden %d campaigns for %s (seen: %d URLs)",
                        hidden,
                        service_name,
                        len(seen_urls),
                    )
                except Exception as e:
                    logger.error(
                        "Failed to hide unseen campaigns for %s: %s",
                        service_name,
                        e,
                    )

                # Mark execution as completed
                update_execution_run(execution_id, status="completed")
                logger.info(
                    "Completed %s: %d URLs processed, %d saved, %d hidden, %d errors",
                    service_name,
                    processed,
                    saved,
                    hidden,
                    errors,
                )
        finally:
            await close_browser()

        # Store results in session state
        ctx.session.state["pipeline_results"] = all_results

        # Export campaigns to JSON
        json_path = self._export_campaigns_json(target_service)

        # Yield summary event
        summary = {
            "total_services": len(payment_methods),
            "total_urls": len(all_results),
            "saved_campaigns": sum(1 for r in all_results if r.get("saved")),
            "hidden_campaigns": total_hidden,
            "errors": sum(1 for r in all_results if r.get("error")),
            "json_output": json_path,
        }

        yield Event(
            author=self.name,
            content=genai_types.Content(
                parts=[
                    genai_types.Part(
                        text=json.dumps(summary, ensure_ascii=False, indent=2)
                    )
                ]
            ),
        )


# Default root agent instance
root_agent = CampaignPipelineAgent(
    name="campaign_pipeline",
    description="Campaign page collection and classification pipeline",
)

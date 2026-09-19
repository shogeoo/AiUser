"""OpenRouter model metadata helpers."""

import httpx

from src.core.config import OPENROUTER_BASE_URL
from src.core.logger import get_logger

logger = get_logger("model_info")


async def get_input_modalities(model: str) -> set[str]:
    """Return input modalities supported by the model, falling back to text-only."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{OPENROUTER_BASE_URL}/models")
            response.raise_for_status()
            models = response.json().get("data", [])

        for item in models:
            if item.get("id") == model:
                return set(item.get("architecture", {}).get("input_modalities", []))

        logger.warning("Model %s not found in the OpenRouter model list.", model)
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Failed to fetch OpenRouter model info for %s: %s", model, e)

    return {"text"}

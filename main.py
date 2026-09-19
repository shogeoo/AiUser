"""Entry point for the AiUser autonomous Telegram agent."""

import asyncio

from src.agent.assistant import TelegramAIAssistant
from src.core.logger import configure_logging, get_logger

# It's better to configure logging at the very beginning
configure_logging()
logger = get_logger("main")


async def main():
    """Main entry point for the assistant."""
    assistant = TelegramAIAssistant()
    if assistant.is_running:
        await assistant.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
    except Exception as e:
        logger.critical("An unhandled exception occurred: %s", e)

"""Application configuration loaded from environment variables and paths."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TG_API_ID = int(os.getenv("TG_API_ID"))
TG_API_HASH = os.getenv("TG_API_HASH")
SESSION_FILE = "session.session"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL_NAME = "z-ai/glm-5.3-flash"

EVENT_BUFFER_TIMEOUT = 10

SYSTEM_PROMPT_PATH = Path("system_prompt.txt")
PERSON_PROMPT_PATH = Path("person_prompt.txt")
CONTEXT_FILE_PATH = Path("context.json")

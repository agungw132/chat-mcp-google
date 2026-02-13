import os

from dotenv import load_dotenv

load_dotenv()

AVAILABLE_MODELS = [
    "deepseek-v3-2-251201",
    "glm-4-7-251222",
    "glm-5",
    "kimi-k2-250905",
    "gemini-3-flash-preview",
    "gemini-3-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

_FALLBACK_DEFAULT_MODEL = "gemini-3-flash-preview"


def resolve_default_model() -> str:
    model_from_env = (os.getenv("MODEL") or "").strip()
    if model_from_env and model_from_env in AVAILABLE_MODELS:
        return model_from_env
    return _FALLBACK_DEFAULT_MODEL


DEFAULT_MODEL = resolve_default_model()

SYSTEM_INSTRUCTION = (
    "Anda adalah asisten AI yang membantu. Gunakan Bahasa Indonesia. "
    "Anda dapat mengakses Gmail, Calendar, dan Contacts melalui alat yang tersedia."
)

OPENAI_SYSTEM_INSTRUCTION = (
    "Anda adalah asisten AI yang membantu. Gunakan Bahasa Indonesia. "
    "Anda dapat mengakses Gmail, Google Calendar, dan Google Contacts melalui alat yang tersedia."
)

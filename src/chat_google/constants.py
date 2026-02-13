import os

from dotenv import load_dotenv

load_dotenv()

AVAILABLE_MODELS = [
    "deepseek-v3-2-251201",
    "deepseek-r1-250528",
    "glm-4-7-251222",
    "glm-5",
    "kimi-k2-250905",
    "kimi-k2-thinking-251104",
    "seed-1-8-251228",
    "whisper-1",
    "azure_ai/kimi-k2.5",
    "gemini-3-flash-preview",
    "gemini-3-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

_FALLBACK_DEFAULT_MODEL = "azure_ai/kimi-k2.5"


def resolve_default_model() -> str:
    model_from_env = (os.getenv("MODEL") or "").strip()
    if model_from_env and model_from_env in AVAILABLE_MODELS:
        return model_from_env
    return _FALLBACK_DEFAULT_MODEL


DEFAULT_MODEL = resolve_default_model()

SYSTEM_INSTRUCTION = (
    "You are a helpful AI assistant. Respond in English. "
    "You can access Gmail, Calendar, Contacts, Drive, and Google Maps using the available tools. "
    "Use tools only when needed and only if relevant to the user request. "
    "Calendar tool capabilities: add_event supports only summary, start_time, duration_minutes, and description. "
    "Calendar tool does not support structured attendees or location fields. "
    "If user requests invite attendees or specific location, include those details in description and clearly state the limitation. "
    "Use Google Maps tools for place search, address lookup, and directions when the user requests location-related tasks."
)

OPENAI_SYSTEM_INSTRUCTION = (
    "You are a helpful AI assistant. Respond in English. "
    "You can access Gmail, Google Calendar, Google Contacts, Google Drive, and Google Maps using the available tools. "
    "Use tools only when needed and only if relevant to the user request. "
    "Google Calendar add_event supports only summary, start_time, duration_minutes, and description. "
    "Google Calendar add_event does not support structured attendees or location fields. "
    "If user requests invite attendees or specific location, include those details in description and clearly state the limitation. "
    "Use Google Maps tools for place search, address lookup, and directions when the user requests location-related tasks."
)

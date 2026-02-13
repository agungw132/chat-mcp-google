from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["gmail", "calendar", "contacts", "drive", "maps"]
    script: str = Field(min_length=1)


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    base_url: str = Field(default="https://ai.sumopod.com", min_length=1)
    api_key: str | None = None
    google_gemini_api_key: str | None = None


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool", "model"]
    content: str = ""


class MetricsRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    request_id: str
    model: str
    user_question: str
    duration_seconds: float
    invoked_tools: list[str]
    invoked_servers: list[str]
    status: str
    error_message: str | None = None
    tool_errors: list[str] = Field(default_factory=list)

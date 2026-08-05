from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    schema_version: int

    mac_agent: bool
    mac_whisper: bool
    server_whisper: bool
    litellm: bool

    active_mac_transcriptions: int
    mac_whisper_idle_seconds: int | None
    whisper_shutdown_after_seconds: int

import os


class Settings:
    mac_host = os.environ.get("MAC_HOST", "192.168.178.58")
    mac_agent_port = int(os.environ.get("MAC_AGENT_PORT", "8010"))
    mac_whisper_port = int(os.environ.get("MAC_WHISPER_PORT", "8001"))
    mac_agent_token = os.environ["MAC_AGENT_TOKEN"]

    server_whisper_url = os.environ.get(
        "SERVER_WHISPER_URL",
        "http://whisper:8000",
    ).rstrip("/")

    mac_whisper_model = os.environ.get(
        "MAC_WHISPER_MODEL",
        "whisper-large-v3-turbo",
    )

    server_whisper_model = os.environ.get(
        "SERVER_WHISPER_MODEL",
        "Systran/faster-whisper-medium",
    )

    whisper_idle_seconds = int(
        os.environ.get("WHISPER_IDLE_SECONDS", "600")
    )

    litellm_url = os.environ.get(
        "LITELLM_URL",
        "http://litellm:4000",
    ).rstrip("/")

    litellm_api_key = os.environ.get(
        "LITELLM_API_KEY",
        "",
    )

    database_path = os.environ.get(
        "DATABASE_PATH",
        "/app/data/queue.db",
    )

    task_worker_poll_seconds = float(
        os.environ.get("TASK_WORKER_POLL_SECONDS", "5")
    )

    mac_memory_limit_percent = float(
        os.environ.get("MAC_MEMORY_LIMIT_PERCENT", "80")
    )

    allow_simultaneous_mac_ai = (
        os.environ.get(
            "ALLOW_SIMULTANEOUS_MAC_AI",
            "false",
        ).strip().lower()
        in {"1", "true", "yes", "on"}
    )

    @property
    def mac_agent_url(self) -> str:
        return f"http://{self.mac_host}:{self.mac_agent_port}"

    @property
    def mac_whisper_url(self) -> str:
        return f"http://{self.mac_host}:{self.mac_whisper_port}"


settings = Settings()

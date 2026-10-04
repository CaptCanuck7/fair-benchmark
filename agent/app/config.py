import os

DEFAULT_ALLOWED_DOMAINS = (
    "nvd.nist.gov,cisa.gov,first.org,attack.mitre.org,cisecurity.org,verizon.com,ibm.com,cyentia.com"
)


def _bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _domains(value: str) -> tuple[str, ...]:
    return tuple(d.strip().lower().lstrip(".") for d in value.split(",") if d.strip())


class Settings:
    # The key is read here and handed to the Anthropic client. It is never
    # logged or returned by any endpoint.
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    anthropic_model: str = os.environ.get("ANTHROPIC_MODEL", "").strip()
    external_enabled: bool = _bool(os.environ.get("AGENT_EXTERNAL_ENABLED", "true"))
    allowed_domains: tuple[str, ...] = _domains(os.environ.get("ALLOWED_DOMAINS") or DEFAULT_ALLOWED_DOMAINS)
    nvd_api_key: str = os.environ.get("NVD_API_KEY", "").strip()
    # The api service, on the internal compose network.
    api_url: str = os.environ.get("API_INTERNAL_URL", "http://api:8000")


settings = Settings()


def not_configured_reason() -> str | None:
    """Why the agent can't run, in words for the analyst, or None if it can."""
    missing = []
    if not settings.anthropic_api_key:
        missing.append("ANTHROPIC_API_KEY")
    if not settings.anthropic_model:
        missing.append("ANTHROPIC_MODEL")
    if missing:
        return (
            f"The agent is turned off because {' and '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} not set. Add {'it' if len(missing) == 1 else 'them'} "
            "to the .env file and restart with docker compose up -d."
        )
    return None

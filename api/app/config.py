import os
from pathlib import Path


class Settings:
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./fair.db")
    cors_origin: str = os.environ.get("CORS_ORIGIN", "http://localhost:8080")
    max_body_bytes: int = int(os.environ.get("MAX_BODY_BYTES", str(1024 * 1024)))
    # Register workbook uploads get their own, larger limit.
    max_upload_bytes: int = int(os.environ.get("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
    # Read-only folder holding mock_internal_evidence.xlsx and reference_library.json.
    agent_data_dir: Path = Path(os.environ.get("AGENT_DATA_DIR", "/agent-data"))
    # The agent service, reachable only on the internal compose network.
    agent_url: str = os.environ.get("AGENT_URL", "http://agent:8001")
    # Baseline score (impact x likelihood) at or above which a ready risk qualifies.
    triage_min_score: int = int(os.environ.get("TRIAGE_MIN_SCORE") or 6)
    # Recorded as the reviewer on approvals and overrides (the app has no sign-in).
    analyst_name: str = (os.environ.get("ANALYST_NAME") or "").strip()
    # Background agent jobs run in a small thread pool. Tests run them inline.
    agent_workers: int = int(os.environ.get("AGENT_WORKERS") or 3)


settings = Settings()

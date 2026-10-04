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


settings = Settings()

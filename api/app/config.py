import os


class Settings:
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./fair.db")
    cors_origin: str = os.environ.get("CORS_ORIGIN", "http://localhost:8080")


settings = Settings()

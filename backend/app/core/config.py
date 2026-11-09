from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.contracts import EmbeddingConfig

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )
    qdrant_url: str = "http://127.0.0.1:6333"
    data_dir: Path = Field(default=ROOT / "data", validation_alias="ASISTENTE_DATA_DIR")
    openalex_api_key: SecretStr | None = None
    embedding_device: str = "cpu"
    embedding_threads: int = Field(default=4, ge=1, le=32)

    @field_validator("data_dir")
    @classmethod
    def absolute_data_path(cls, value: Path) -> Path:
        return (ROOT / value).resolve() if not value.is_absolute() else value.resolve()


def embedding_config() -> EmbeddingConfig:
    return EmbeddingConfig.model_validate_json((ROOT / "config/embedding.json").read_text("utf-8"))

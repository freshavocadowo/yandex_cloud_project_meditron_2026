from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="config/.env", env_file_encoding="utf-8", extra="ignore")
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="YANDEX_API_KEY")
    folder_id: str = Field(default="", validation_alias="YANDEX_FOLDER_ID")
    model: str = Field(default="yandexgpt/5.1", validation_alias="YANDEX_MODEL")
    timeout_seconds: float = Field(default=90, gt=0, validation_alias="STATCHEM_TIMEOUT_SECONDS")
    max_tokens: int = Field(default=12000, gt=0, validation_alias="STATCHEM_MAX_TOKENS")
    use_ner: bool = Field(default=True, validation_alias="STATCHEM_USE_NER")

    def require_cloud(self):
        if not self.api_key.get_secret_value() or not self.folder_id:
            raise ValueError("missing_yandex_configuration")
        if not self.use_ner:
            raise ValueError("cloud_requires_local_ner")

    @property
    def model_uri(self):
        return self.model if self.model.startswith("gpt://") else f"gpt://{self.folder_id}/{self.model}"

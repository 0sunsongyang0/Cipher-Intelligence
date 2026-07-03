from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "兔兔炸弹的大模型助手"
    app_access_password: str = "change-me"
    session_secret: str = "change-me-too"
    deepseek_api_key: str = "unset"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    database_url: str = "sqlite:///./backend/data/app.db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

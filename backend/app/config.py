from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "\u5154\u5154\u70b8\u5f39\u7684\u5927\u6a21\u578b\u52a9\u624b"
    app_env: str = "development"
    app_access_password: str = "change-me"
    session_secret: str = "change-me-too"
    session_cookie_secure: bool | None = None
    deepseek_api_key: str = "unset"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    database_url: str = "sqlite:///./backend/data/app.db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def __init__(self, **values):
        super().__init__(**values)
        if self.app_env not in {"development", "test"} and (
            self.app_access_password == "change-me"
            or self.session_secret == "change-me-too"
        ):
            raise ValueError(
                "default auth secrets are not allowed outside explicit test/development mode"
            )

    @property
    def session_cookie_secure_enabled(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.app_env == "production"


settings = Settings()

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. AgentHub-specific vars use the AGENTHUB_ prefix;
    LLM provider keys use their conventional names (ANTHROPIC_API_KEY, ...)."""

    model_config = SettingsConfigDict(env_prefix="AGENTHUB_", env_file=".env", extra="ignore")

    app_name: str = "AgentHub"
    version: str = "0.1.0"

    database_url: str = "sqlite:///./agenthub.db"
    # Demo mode: seeds a read-only public account and resets data on start.
    demo_mode: bool = True
    cors_origins: list[str] = ["http://localhost:4200"]

    jwt_secret: str = "dev-only-insecure-secret-change-me-in-production"
    jwt_ttl_minutes: int = 60 * 12

    admin_username: str = "admin"
    admin_password: str = "admin"
    demo_username: str = "demo"
    demo_password: str = "demo"
    # Raw key the bundled Research Crew uses to authenticate to the gateway.
    crew_api_key: str = "ah_demo_research_crew_key"

    @field_validator("crew_api_key")
    @classmethod
    def _key_prefix(cls, v: str) -> str:
        # API keys are recognised by their "ah_" prefix; a generated secret (e.g. Render's) has none.
        return v if v.startswith("ah_") else "ah_" + v

    # Registering a stdio MCP server makes the backend execute a command. Off by default so a
    # public deployment can't be turned into remote code execution; seeded servers are unaffected.
    allow_stdio_registration: bool = False

    rate_limit_per_minute: int = 120
    tool_timeout_seconds: float = 15.0

    # LLM gateway. Provider is auto-picked from whichever key is set unless forced here
    # (anthropic | google | groq | openai | ollama | scripted).
    llm_provider: str | None = None
    llm_model: str | None = None
    ollama_url: str = "http://localhost:11434/v1"
    llm_timeout_seconds: float = 45.0
    llm_mask_pii: bool = True

    # LLM providers (optional). Without any of these the LLM gateway runs in scripted mode.
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    groq_api_key: str | None = Field(default=None, validation_alias="GROQ_API_KEY")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()

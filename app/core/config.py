from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ResearchOps Agent"
    app_version: str = "0.1.0"
    openai_api_key: str | None = None
    database_url: str = "postgresql+psycopg://researchops:researchops@localhost:5432/researchops"
    redis_url: str = "redis://localhost:6379/0"
    vector_backend: str = "pgvector"
    reranker_provider: str = "none"
    embedding_provider: str = "local"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 384
    agent_runtime: str = "auto"
    openai_agent_model: str = "gpt-5-nano"
    mcp_servers_json: str = "[]"
    mcp_allowed_tools_json: str = "{}"
    mcp_timeout_seconds: int = 8
    api_keys_json: str = "[]"
    local_users_json: str = "[]"
    auth_required: bool = False
    session_ttl_seconds: int = 28_800
    default_tenant_id: str = "default"
    sandbox_mode: str = "process"
    sandbox_docker_image: str = "python:3.12-slim"
    sandbox_memory: str = "128m"
    sandbox_cpus: str = "0.5"
    sandbox_timeout_seconds: int = 3
    sandbox_max_output_chars: int = 4000
    store_backend: str = "auto"
    app_env: str = "local"
    log_level: str = "INFO"
    data_dir: str = "data"
    max_upload_bytes: int = 10_000_000
    retrieval_top_k: int = 5
    url_fetch_allowlist_json: str = "[]"
    url_fetch_timeout_seconds: int = 15
    url_fetch_max_redirects: int = 3
    task_backend: str = "local"
    agent_max_tool_calls: int = 4
    github_repo_file_max_bytes: int = 80_000
    github_repo_max_text_chars: int = 500_000


settings = Settings()

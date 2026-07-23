from __future__ import annotations

from dataclasses import dataclass
import os
import secrets

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass


_INSECURE_AUTH_SECRET = "edumatrix_super_secret_v1_2026"


def _load_auth_secret_key() -> str:
    """Require an explicit strong key in production and isolate dev tokens."""
    configured = os.getenv("EDUMATRIX_AUTH_SECRET_KEY", "").strip()
    environment = os.getenv("EDUMATRIX_ENV", "development").strip().lower()
    if environment in {"production", "prod"}:
        if not configured or configured == _INSECURE_AUTH_SECRET or len(configured) < 32:
            raise RuntimeError(
                "EDUMATRIX_AUTH_SECRET_KEY must be a unique value of at least 32 characters in production"
            )
        return configured
    if not configured or configured == _INSECURE_AUTH_SECRET:
        return secrets.token_urlsafe(32)
    return configured


@dataclass(frozen=True)
class EduMatrixConfig:
    spark_app_id: str = os.getenv("SPARK_APP_ID", "")
    spark_api_key: str = os.getenv("SPARK_API_KEY", "")
    spark_api_secret: str = os.getenv("SPARK_API_SECRET", "")
    spark_url: str = os.getenv("SPARK_URL", "wss://spark-api.xf-yun.com/v3.5/chat")
    spark_domain: str = os.getenv("SPARK_DOMAIN", "generalv3.5")

    llm_provider: str = os.getenv("EDUMATRIX_LLM_PROVIDER", "deterministic")
    llm_endpoint: str = os.getenv("EDUMATRIX_LLM_ENDPOINT", "")
    llm_api_key: str = os.getenv("EDUMATRIX_LLM_API_KEY", "")
    llm_model: str = os.getenv("EDUMATRIX_LLM_MODEL", "deterministic")
    llm_temperature: float = float(os.getenv("EDUMATRIX_LLM_TEMPERATURE", "0.3"))
    llm_max_tokens: int = int(os.getenv("EDUMATRIX_LLM_MAX_TOKENS", "8192"))
    llm_timeout: int = int(os.getenv("EDUMATRIX_LLM_TIMEOUT", "120"))

    # Configs for fallback multimodal LLM
    multimodal_llm_provider: str = os.getenv("EDUMATRIX_MULTIMODAL_LLM_PROVIDER", "")
    multimodal_llm_endpoint: str = os.getenv("EDUMATRIX_MULTIMODAL_LLM_ENDPOINT", "")
    multimodal_llm_api_key: str = os.getenv("EDUMATRIX_MULTIMODAL_LLM_API_KEY", "")
    multimodal_llm_model: str = os.getenv("EDUMATRIX_MULTIMODAL_LLM_MODEL", "")

    retrieval_top_k: int = int(os.getenv("EDUMATRIX_TOP_K", "6"))
    debate_min_score: float = float(os.getenv("EDUMATRIX_DEBATE_MIN_SCORE", "0.42"))
    alignment_threshold: float = float(os.getenv("EDUMATRIX_ALIGNMENT_THRESHOLD", "0.65"))
    rollback_limit: int = int(os.getenv("EDUMATRIX_ROLLBACK_LIMIT", "2"))

    embedding_provider: str = os.getenv("EDUMATRIX_EMBEDDING_PROVIDER", "hash")
    embedding_endpoint: str = os.getenv("EDUMATRIX_EMBEDDING_ENDPOINT", "")
    embedding_api_key: str = os.getenv("EDUMATRIX_EMBEDDING_API_KEY", "")
    embedding_model: str = os.getenv("EDUMATRIX_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    embedding_dim: int = int(os.getenv("EDUMATRIX_EMBEDDING_DIM", "384"))

    use_faiss: bool = os.getenv("EDUMATRIX_USE_FAISS", "0") == "1"
    faiss_index_dir: str = os.getenv("EDUMATRIX_FAISS_DIR", "data/faiss_indexes")

    max_concurrent_llm: int = int(os.getenv("EDUMATRIX_MAX_CONCURRENT_LLM", "8"))
    llm_rate_limit_rpm: int = int(os.getenv("EDUMATRIX_LLM_RATE_LIMIT_RPM", "120"))
    llm_rate_limit_tpm: int = int(os.getenv("EDUMATRIX_LLM_RATE_LIMIT_TPM", "100000"))
    llm_circuit_breaker_threshold: int = int(os.getenv("EDUMATRIX_CIRCUIT_BREAKER_THRESHOLD", "5"))
    llm_circuit_breaker_window: int = int(os.getenv("EDUMATRIX_CIRCUIT_BREAKER_WINDOW", "60"))
    llm_retry_max_attempts: int = int(os.getenv("EDUMATRIX_RETRY_MAX_ATTEMPTS", "3"))
    llm_request_queue_size: int = int(os.getenv("EDUMATRIX_REQUEST_QUEUE_SIZE", "200"))

    # In-process cache governance. Every cache using these defaults is bounded
    # and expires entries instead of growing for the lifetime of the process.
    cache_max_entries: int = int(os.getenv("EDUMATRIX_CACHE_MAX_ENTRIES", "256"))
    cache_ttl_seconds: float = float(os.getenv("EDUMATRIX_CACHE_TTL_SECONDS", "900"))
    search_cache_max_entries: int = int(os.getenv("EDUMATRIX_SEARCH_CACHE_MAX_ENTRIES", "128"))

    # Document safety limits. Raw upload size is enforced separately; these
    # limits also protect parser/ZIP/PDF work from resource exhaustion.
    max_document_pages: int = int(os.getenv("EDUMATRIX_MAX_DOCUMENT_PAGES", "200"))
    max_archive_members: int = int(os.getenv("EDUMATRIX_MAX_ARCHIVE_MEMBERS", "2000"))
    max_archive_uncompressed_bytes: int = int(os.getenv("EDUMATRIX_MAX_ARCHIVE_UNCOMPRESSED_BYTES", str(100 * 1024 * 1024)))
    document_parse_timeout: float = float(os.getenv("EDUMATRIX_DOCUMENT_PARSE_TIMEOUT", "45"))
    max_web_content_chars: int = int(os.getenv("EDUMATRIX_MAX_WEB_CONTENT_CHARS", "200000"))

    # Neo4j Graph Database
    neo4j_uri: str = os.getenv("EDUMATRIX_NEO4J_URI", "")
    neo4j_user: str = os.getenv("EDUMATRIX_NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("EDUMATRIX_NEO4J_PASSWORD", "")
    neo4j_database: str = os.getenv("EDUMATRIX_NEO4J_DATABASE", "neo4j")

    # ChromaDB Vector Store
    use_chromadb: bool = os.getenv("EDUMATRIX_USE_CHROMADB", "0") == "1"
    chroma_persist_dir: str = os.getenv("EDUMATRIX_CHROMA_DIR", "data/chroma_db")
    chroma_collection_formulas: str = os.getenv("EDUMATRIX_CHROMA_FORMULAS", "edumatrix_formulas")

    # Auth Settings
    auth_secret_key: str = _load_auth_secret_key()
    auth_algorithm: str = os.getenv("EDUMATRIX_AUTH_ALGORITHM", "HS256")
    auth_access_token_expire_minutes: int = int(os.getenv("EDUMATRIX_AUTH_TOKEN_EXPIRE_MINS", "1440")) # Default 24 hours
    demo_mode: bool = os.getenv("EDUMATRIX_DEMO_MODE", "0") == "1"

    # Sandbox Settings. trusted_local is a research/demo mode: it uses a
    # restricted child process but does not provide container isolation.
    sandbox_mode: str = os.getenv("EDUMATRIX_SANDBOX_MODE", "disabled").strip().lower()
    sandbox_timeout: float = float(os.getenv("EDUMATRIX_SANDBOX_TIMEOUT", "10.0"))
    sandbox_max_output_bytes: int = int(os.getenv("EDUMATRIX_SANDBOX_MAX_OUTPUT_BYTES", "100000"))
    sandbox_max_visual_bytes: int = int(os.getenv("EDUMATRIX_SANDBOX_MAX_VISUAL_BYTES", "5000000"))
    max_upload_bytes: int = int(os.getenv("EDUMATRIX_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))



CONFIG = EduMatrixConfig()

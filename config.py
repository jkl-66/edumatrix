from __future__ import annotations

from dataclasses import dataclass
import os

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass


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
    auth_secret_key: str = os.getenv("EDUMATRIX_AUTH_SECRET_KEY", "edumatrix_super_secret_v1_2026")
    auth_algorithm: str = os.getenv("EDUMATRIX_AUTH_ALGORITHM", "HS256")
    auth_access_token_expire_minutes: int = int(os.getenv("EDUMATRIX_AUTH_TOKEN_EXPIRE_MINS", "1440")) # Default 24 hours

    # Sandbox Settings
    sandbox_timeout: float = float(os.getenv("EDUMATRIX_SANDBOX_TIMEOUT", "10.0"))



CONFIG = EduMatrixConfig()

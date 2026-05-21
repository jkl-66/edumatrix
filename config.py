from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class EduMatrixConfig:
    """Runtime switches for the EduMatrix pipeline.

    The default configuration is intentionally runnable on a laptop. Production
    deployments can replace the in-memory graph/vector indexes with Neo4j,
    Milvus/FAISS, SparkDesk, and virtual-human services through these knobs.
    """

    spark_app_id: str = os.getenv("SPARK_APP_ID", "")
    spark_api_key: str = os.getenv("SPARK_API_KEY", "")
    spark_api_secret: str = os.getenv("SPARK_API_SECRET", "")
    spark_url: str = os.getenv("SPARK_URL", "wss://spark-api.xf-yun.com/v3.5/chat")
    spark_domain: str = os.getenv("SPARK_DOMAIN", "generalv3.5")

    retrieval_top_k: int = int(os.getenv("EDUMATRIX_TOP_K", "6"))
    debate_min_score: float = float(os.getenv("EDUMATRIX_DEBATE_MIN_SCORE", "0.42"))
    alignment_threshold: float = float(os.getenv("EDUMATRIX_ALIGNMENT_THRESHOLD", "2.60"))
    rollback_limit: int = int(os.getenv("EDUMATRIX_ROLLBACK_LIMIT", "2"))

    use_remote_llm: bool = os.getenv("EDUMATRIX_USE_REMOTE_LLM", "0") == "1"

    embedding_provider: str = os.getenv("EDUMATRIX_EMBEDDING_PROVIDER", "local")
    embedding_endpoint: str = os.getenv("EDUMATRIX_EMBEDDING_ENDPOINT", "")
    embedding_api_key: str = os.getenv("EDUMATRIX_EMBEDDING_API_KEY", "")
    embedding_model: str = os.getenv("EDUMATRIX_EMBEDDING_MODEL", "text-embedding-3-large")
    embedding_dim: int = int(os.getenv("EDUMATRIX_EMBEDDING_DIM", "384"))

    use_faiss: bool = os.getenv("EDUMATRIX_USE_FAISS", "1") == "1"
    faiss_index_dir: str = os.getenv("EDUMATRIX_FAISS_DIR", "data/faiss_indexes")


CONFIG = EduMatrixConfig()

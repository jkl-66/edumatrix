"""集中异常模块（替代抛裸 HTTPException / RuntimeError）。"""

from __future__ import annotations


class EduMatrixUtilError(Exception):
    """工具子系统统一基类。"""


class GraphBuilderError(EduMatrixUtilError):
    """图谱构建（三元组抽取 / Neo4j 写入 / 实体对齐）类异常。"""


class TripletExtractionError(GraphBuilderError):
    """LLM 返回非约束 JSON / 解析失败。"""


class GraphRepositoryError(GraphBuilderError):
    """Neo4j 或图存储后端写入失败。"""


class FormulaExtractionError(EduMatrixUtilError):
    """Layout/OCR 公式抽取失败。"""


class FormulaIndexError(EduMatrixUtilError):
    """公式向量库读写失败。"""

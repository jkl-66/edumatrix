"""Layout 分析与公式 LaTeX 抽取模块。

职责:
  1. 从课件/课本图像中检测公式区域 (LayoutLMv3 / 规则降级)
  2. 将公式区域转换为 LaTeX 标准串 (Pix2Text / 规则降级)
  3. 生成 Jinja2 增强格式文本: [LaTeX_Source: ...] (公式语义解释: ...)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.utils.exceptions import FormulaExtractionError
from embedding_models import EMBEDDINGS
from models import Evidence, EvidenceModality


@dataclass(frozen=True)
class FormulaRegion:
    """图像中检测到的公式区域。"""
    bbox: tuple[int, int, int, int]  # (x0, y0, x1, y1)
    confidence: float
    page: int = 0


@dataclass(frozen=True)
class ExtractedFormula:
    """从图像中提取的公式结果。"""
    latex_source: str
    semantic_text: str
    bbox: tuple[int, int, int, int]
    confidence: float
    page: int = 0
    source_file: str = ""

    def enhanced_text(self) -> str:
        """生成 Jinja2 增强格式: [LaTeX_Source: ...] (公式语义解释: ...)"""
        latex = self.latex_source.strip()
        if not latex.startswith("$$"):
            latex = f"$${latex}$$"
        return f"[LaTeX_Source: {latex}] (公式语义解释: {self.semantic_text})"


class LayoutAnalyzer:
    """公式区域检测器。优先使用 LayoutLMv3, 降级使用规则引擎。"""

    def detect_formulas(self, image_input: Any) -> tuple[FormulaRegion, ...]:
        """检测图像中的公式区域。

        Args:
            image_input: 图像路径 (str/Path) 或 PIL Image 对象
        """
        try:
            return self._detect_with_layoutlm(image_input)
        except Exception:
            return self._detect_with_rules(image_input)

    def _detect_with_layoutlm(self, image_input: Any) -> tuple[FormulaRegion, ...]:
        """LayoutLMv3 公式区域检测。"""
        try:
            from transformers import LayoutLMv3Processor, LayoutLMv3ForTokenClassification
            import torch
            from PIL import Image

            img = Image.open(image_input) if isinstance(image_input, (str, bytes)) else image_input
            processor = LayoutLMv3Processor.from_pretrained("microsoft/layoutlmv3-base", apply_ocr=True)
            model = LayoutLMv3ForTokenClassification.from_pretrained("microsoft/layoutlmv3-base")

            encoding = processor(img, return_tensors="pt")
            with torch.no_grad():
                outputs = model(**encoding)

            # Parse token-level predictions into bounding boxes
            regions: list[FormulaRegion] = []
            predictions = outputs.logits.argmax(-1).squeeze().tolist()
            if hasattr(encoding, "bbox") and encoding.bbox is not None:
                bboxes = encoding.bbox.squeeze().tolist()
                in_formula = False
                formula_start = 0
                for idx, (pred, bbox) in enumerate(zip(predictions, bboxes)):
                    if pred == 1 and not in_formula:  # formula label
                        in_formula = True
                        formula_start = idx
                    elif pred != 1 and in_formula:
                        x0 = min(bboxes[j][0] for j in range(formula_start, idx) if j < len(bboxes))
                        y0 = min(bboxes[j][1] for j in range(formula_start, idx) if j < len(bboxes))
                        x1 = max(bboxes[j][2] for j in range(formula_start, idx) if j < len(bboxes))
                        y1 = max(bboxes[j][3] for j in range(formula_start, idx) if j < len(bboxes))
                        regions.append(FormulaRegion(bbox=(x0, y0, x1, y1), confidence=0.85))
                        in_formula = False

            return tuple(regions) if regions else self._detect_with_rules(image_input)
        except ImportError:
            raise FormulaExtractionError("LayoutLMv3 依赖未安装")

    def _detect_with_rules(self, image_input: Any) -> tuple[FormulaRegion, ...]:
        """规则引擎降级: 返回全图区域作为公式候选。"""
        try:
            from PIL import Image
            img = Image.open(image_input) if isinstance(image_input, (str, bytes)) else image_input
            w, h = img.size
            return (FormulaRegion(bbox=(0, 0, w, h), confidence=0.3),)
        except Exception:
            return (FormulaRegion(bbox=(0, 0, 800, 600), confidence=0.2),)


class FormulaOCREngine:
    """LaTeX 公式 OCR 引擎。优先使用 Pix2Text, 降级使用正则/规则方法。"""

    def extract_latex(self, image_input: Any, region: FormulaRegion | None = None) -> ExtractedFormula:
        """从图像或裁剪区域提取 LaTeX 公式。"""
        try:
            return self._extract_with_pix2text(image_input, region)
        except Exception:
            return self._extract_with_regex(image_input, region)

    def _extract_with_pix2text(self, image_input: Any, region: FormulaRegion | None = None) -> ExtractedFormula:
        """Pix2Text LaTeX 提取。"""
        try:
            from pix2text import Pix2Text
            from PIL import Image

            img = Image.open(image_input) if isinstance(image_input, (str, bytes)) else image_input
            if region is not None:
                x0, y0, x1, y1 = region.bbox
                img = img.crop((x0, y0, x1, y1))

            p2t = Pix2Text()
            result = p2t.recognize(img)
            latex = result.get("latex", "") if isinstance(result, dict) else str(result)

            semantic = _latex_to_semantic(latex)
            confidence = region.confidence if region else 0.9
            bbox = region.bbox if region else (0, 0, img.size[0], img.size[1])
            page = region.page if region else 0

            return ExtractedFormula(
                latex_source=latex.strip(),
                semantic_text=semantic,
                bbox=bbox,
                confidence=confidence,
                page=page,
            )
        except ImportError:
            raise FormulaExtractionError("Pix2Text 依赖未安装")

    def _extract_with_regex(self, image_input: Any, region: FormulaRegion | None = None) -> ExtractedFormula:
        """正则降级: 从文件名或路径推断公式内容。"""
        # Try to extract from text if the input is a text string
        if isinstance(image_input, str):
            latex_matches = re.findall(r"\$\$(.+?)\$\$", image_input, re.DOTALL)
            if latex_matches:
                latex = latex_matches[0]
                semantic = _latex_to_semantic(latex)
                bbox = region.bbox if region else (0, 0, 100, 50)
                confidence = region.confidence if region else 0.5
                return ExtractedFormula(latex_source=latex, semantic_text=semantic, bbox=bbox, confidence=confidence)

        # Ultimate fallback
        bbox = region.bbox if region else (0, 0, 100, 50)
        confidence = region.confidence if region else 0.1
        return ExtractedFormula(
            latex_source="",
            semantic_text="公式提取降级: 无法识别",
            bbox=bbox,
            confidence=confidence,
        )


# ---------------------------------------------------------------------------
# LaTeX -> semantic text conversion
# ---------------------------------------------------------------------------
LATEX_SEMANTIC_MAP = {
    r"\\frac\{(.+?)\}\{(.+?)\}": lambda m: f"{m.group(1)}除以{m.group(2)}",
    r"\\partial": "偏导数",
    r"\\nabla": "梯度",
    r"\\sum": "求和",
    r"\\prod": "求积",
    r"\\int": "积分",
    r"\\lim": "极限",
    r"\\sqrt\{(.+?)\}": lambda m: f"{m.group(1)}的平方根",
    r"\\hat\{(.+?)\}": lambda m: f"{m.group(1)}的估计值",
    r"\\bar\{(.+?)\}": lambda m: f"{m.group(1)}的均值",
    r"\\dot\{(.+?)\}": lambda m: f"{m.group(1)}的导数",
    r"\\log": "对数",
    r"\\exp": "指数",
    r"\\sin": "正弦",
    r"\\cos": "余弦",
    r"\\theta": "theta",
    r"\\alpha": "alpha",
    r"\\beta": "beta",
    r"\\gamma": "gamma",
    r"\\lambda": "lambda",
    r"\\sigma": "sigma",
    r"\\mu": "mu",
    r"\\Omega": "Omega",
}


def _latex_to_semantic(latex: str) -> str:
    """将 LaTeX 公式源码转换为中文自然语言语义描述。"""
    if not latex:
        return "未知公式"
    result = latex
    # Apply pattern replacements
    for pattern, replacement in LATEX_SEMANTIC_MAP.items():
        if callable(replacement):
            result = re.sub(pattern, replacement, result)
        else:
            result = re.sub(pattern, replacement, result)
    # Strip remaining LaTeX commands
    result = re.sub(r"\\[a-zA-Z]+", "", result)
    # Clean up braces and whitespace
    result = re.sub(r"[{}]", "", result)
    result = re.sub(r"\s+", " ", result).strip()
    # If result is too short, provide generic description
    if len(result) < 3:
        return "数学公式"
    return result


# ---------------------------------------------------------------------------
# Main extraction pipeline
# ---------------------------------------------------------------------------
class FormulaExtractor:
    """公式提取管道: Layout 分析 -> OCR -> 增强格式。"""

    def __init__(
        self,
        layout_analyzer: LayoutAnalyzer | None = None,
        ocr_engine: FormulaOCREngine | None = None,
    ) -> None:
        self.layout_analyzer = layout_analyzer or LayoutAnalyzer()
        self.ocr_engine = ocr_engine or FormulaOCREngine()

    def extract_from_image(
        self,
        image_input: Any,
        *,
        source_file: str = "",
    ) -> tuple[ExtractedFormula, ...]:
        """从图像中提取所有公式。"""
        regions = self.layout_analyzer.detect_formulas(image_input)
        formulas: list[ExtractedFormula] = []
        for region in regions:
            formula = self.ocr_engine.extract_latex(image_input, region)
            formulas.append(ExtractedFormula(
                latex_source=formula.latex_source,
                semantic_text=formula.semantic_text,
                bbox=formula.bbox,
                confidence=formula.confidence,
                page=formula.page,
                source_file=source_file,
            ))
        return tuple(formulas)

    def extract_from_text(self, text: str, *, source_file: str = "") -> tuple[ExtractedFormula, ...]:
        """从文本中提取已有的 LaTeX 公式 (不依赖 OCR)。"""
        formulas: list[ExtractedFormula] = []
        # Match $$...$$ and $...$ patterns
        for match in re.finditer(r"\$\$(.+?)\$\$", text, re.DOTALL):
            latex = match.group(1).strip()
            semantic = _latex_to_semantic(latex)
            formulas.append(ExtractedFormula(
                latex_source=latex,
                semantic_text=semantic,
                bbox=(0, 0, 0, 0),
                confidence=0.95,
                source_file=source_file,
            ))
        for match in re.finditer(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", text, re.DOTALL):
            latex = match.group(1).strip()
            if not any(latex in f.latex_source for f in formulas):
                semantic = _latex_to_semantic(latex)
                formulas.append(ExtractedFormula(
                    latex_source=latex,
                    semantic_text=semantic,
                    bbox=(0, 0, 0, 0),
                    confidence=0.90,
                    source_file=source_file,
                ))
        return tuple(formulas)

    def formula_to_evidence(
        self,
        formula: ExtractedFormula,
        *,
        chunk_id: str = "",
        source: str = "",
    ) -> Evidence:
        """将提取的公式转换为 Evidence 对象 (用于双轨嵌入)。"""
        fid = chunk_id or f"FORMULA_{hash(formula.latex_source) % 100000:05d}"
        enhanced = formula.enhanced_text()
        return Evidence(
            id=fid,
            title=f"公式: {formula.semantic_text[:60]}",
            content=enhanced,
            modality=EvidenceModality.IMAGE,
            source=source or formula.source_file,
            tags=("公式", "LaTeX", "数学表达式"),
            anchors=(formula.latex_source[:40], formula.semantic_text[:30]),
            metadata={
                "latex_source": formula.latex_source,
                "semantic_text": formula.semantic_text,
                "bbox": list(formula.bbox),
                "formula_confidence": formula.confidence,
                "page": formula.page,
            },
        )

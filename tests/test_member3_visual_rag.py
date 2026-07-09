"""成员 3 Task 1: 多模态视觉文档 RAG 管道测试"""
import os

os.environ["EDUMATRIX_LLM_PROVIDER"] = "mock"
os.environ["EDUMATRIX_EMBEDDING_PROVIDER"] = "hash"

import unittest
from io import BytesIO
from pathlib import Path


class TestVisualDocumentRAG(unittest.TestCase):
    """视觉文档 RAG 管道测试"""

    def test_render_pdf_pages_to_images(self):
        """验证 PyMuPDF 将 PDF 页面渲染为 PNG 图像"""
        from document_parser import _render_pdf_to_images

        # 创建一个最小化的有效 PDF（跨平台兼容）
        pdf_bytes = _create_minimal_pdf()
        pages = _render_pdf_to_images(pdf_bytes, dpi=72)

        # 如果 fitz 可用，应该返回至少 1 页
        try:
            import fitz
            self.assertGreaterEqual(len(pages), 1, "PDF 至少应有 1 页被渲染")
            self.assertIn("image_bytes", pages[0])
            self.assertGreater(len(pages[0]["image_bytes"]), 100, "PNG 图片应大于 100 bytes")
            self.assertIn("page", pages[0])
            self.assertEqual(pages[0]["page"], 1)
        except ImportError:
            # fitz 不可用时返回空列表（优雅降级）
            self.assertEqual(len(pages), 0, "无 fitz 时应返回空列表")

    def test_render_corrupt_pdf_graceful(self):
        """验证损坏的 PDF 不会导致崩溃"""
        from document_parser import _render_pdf_to_images
        pages = _render_pdf_to_images(b"not a valid pdf at all", dpi=72)
        self.assertIsInstance(pages, list)
        # 损坏文件应该返回空列表

    def test_describe_image_fallback_no_vision_llm(self):
        """验证无多模态 LLM 时的降级描述"""
        from document_parser import _describe_image_with_pil

        # 创建一个最小 PNG（1x1 红色像素）
        img_bytes = _create_minimal_png()
        desc = _describe_image_with_pil(img_bytes)

        self.assertIsInstance(desc, str)
        self.assertGreater(len(desc), 10, "降级描述不应为空")
        # 至少应包含文件类型信息
        self.assertTrue("PNG" in desc or "png" in desc or "图片" in desc,
                       f"描述应包含图片类型信息，得到: {desc}")

    def test_parse_pdf_visually_returns_evidence(self):
        """验证 parse_pdf_visually 返回 Evidence 列表"""
        from document_parser import parse_pdf_visually

        pdf_bytes = _create_minimal_pdf()
        evidence_list = parse_pdf_visually(pdf_bytes, "test.pdf")

        self.assertIsInstance(evidence_list, list)
        try:
            import fitz
            # fitz 可用时应该有至少 1 条 evidence
            self.assertGreater(len(evidence_list), 0)
            ev = evidence_list[0]
            self.assertEqual(ev.modality.value, "image")
            self.assertIn("test.pdf", ev.title)
        except ImportError:
            # 无 fitz 时返回空列表
            pass

    def test_vision_check_cached(self):
        """验证多模态 LLM 检测结果被缓存"""
        from document_parser import _check_vision_llm

        result1 = _check_vision_llm()
        result2 = _check_vision_llm()  # 第二次应使用缓存
        self.assertEqual(result1, result2, "两次调用结果应一致（缓存机制）")

    def test_render_pdf_invalid_dpi_handling(self):
        """验证无效 DPI 参数不会导致崩溃"""
        from document_parser import _render_pdf_to_images

        pdf_bytes = _create_minimal_pdf()
        pages_low = _render_pdf_to_images(pdf_bytes, dpi=10)
        self.assertIsInstance(pages_low, list)

    def test_empty_pdf_no_pages(self):
        """验证空 PDF 的处理"""
        from document_parser import _render_pdf_to_images

        pages = _render_pdf_to_images(b"", dpi=72)
        self.assertEqual(len(pages), 0, "空 PDF 应返回空列表")


# ── 辅助函数 ──

def _create_minimal_pdf() -> bytes:
    """创建一个最小化的合法 PDF 文件（用于测试）。"""
    # 使用纯文本构造最小的 PDF
    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n190\n%%EOF"
    )
    return pdf_content


def _create_minimal_png() -> bytes:
    """创建一个最小化的合法 PNG 文件（1x1 红色像素）。"""
    import struct
    import zlib

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    # 1x1 红色像素 (RGB)
    raw_data = b"\x00\xff\x00\x00"  # filter byte + red pixel
    idat = chunk(b"IDAT", zlib.compress(raw_data))
    iend = chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


if __name__ == "__main__":
    unittest.main()

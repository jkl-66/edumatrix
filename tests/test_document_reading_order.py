from io import BytesIO

from docx import Document

from document_parser import parse_document


def interleaved_lesson_bytes():
    """Synthetic lesson: each explanation refers to its immediately preceding table."""
    doc = Document()
    doc.add_heading("比较训练误差和验证误差", level=1)
    doc.add_paragraph("先比较第一轮训练的结果。")
    table = doc.add_table(rows=2, cols=2)
    for cell, value in zip(table._cells, ["训练误差", "验证误差", "0.20", "0.25"]):
        cell.text = value
    doc.add_paragraph("第一张表中，两种误差接近。")
    doc.add_paragraph("")
    doc.add_heading("继续训练后的变化", level=2)
    table = doc.add_table(rows=2, cols=2)
    for cell, value in zip(table._cells, ["训练误差", "验证误差", "0.05", "0.40"]):
        cell.text = value
    doc.add_paragraph("第二张表中，训练误差下降而验证误差上升，应检查过拟合。")
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def test_docx_tables_stay_with_their_explanations_and_source_locations():
    parsed = parse_document(interleaved_lesson_bytes(), "测试用-交错表格.docx")
    expected = [
        "比较训练误差和验证误差",
        "先比较第一轮训练的结果。",
        "训练误差 | 验证误差\n0.20 | 0.25",
        "第一张表中，两种误差接近。",
        "继续训练后的变化",
        "训练误差 | 验证误差\n0.05 | 0.40",
        "第二张表中，训练误差下降而验证误差上升，应检查过拟合。",
    ]
    assert parsed.text == "\n\n".join(expected)
    assert [parsed.text[loc.char_start:loc.char_end] for loc in parsed.locations] == expected
    assert [(loc.kind, loc.index) for loc in parsed.locations] == [
        ("paragraph", 1), ("paragraph", 2), ("table", 1),
        ("paragraph", 3), ("paragraph", 5), ("table", 2), ("paragraph", 6),
    ]


def test_docx_heading_indices_and_counts_survive_interleaved_tables():
    parsed = parse_document(interleaved_lesson_bytes(), "测试用-交错表格.docx")
    assert parsed.metadata["paragraph_count"] == 5
    assert parsed.metadata["table_count"] == 2
    assert [(h["index"], h["heading_level"]) for h in parsed.metadata["heading_candidates"]] == [(1, 1), (5, 2)]
    assert len(parsed.metadata["paragraphs"]) == 6
    assert parsed.metadata["paragraphs"][3]["text"] == ""

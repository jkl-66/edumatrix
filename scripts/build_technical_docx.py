"""Convert the verified Markdown technical manuscript into a handoff DOCX."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs" / "EduMatrix_完整技术文档总稿.md"
OUTPUT = ROOT / "outputs" / "EduMatrix_完整技术文档_可提交版.docx"
SCREENSHOTS = ROOT / "outputs" / "e2e_no_docker"


def set_cell_text(cell, text: str) -> None:
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(text.strip())
    run.font.name = "Microsoft YaHei"
    run.font.size = Pt(8.5)


def add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run("第 ")
    run.font.name = "Microsoft YaHei"
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = "PAGE"
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.append(fld_char1)
    run._r.append(instr_text)
    run._r.append(fld_char2)
    tail = paragraph.add_run(" 页")
    tail.font.name = "Microsoft YaHei"


def add_toc(paragraph) -> None:
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = 'TOC \\o "1-3" \\h \\z \\u'
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "打开 Word 后右键更新目录"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.extend([fld_begin, instr, fld_sep, text, fld_end])


def add_code(doc: Document, code: str) -> None:
    p = doc.add_paragraph(style="No Spacing")
    p.paragraph_format.left_indent = Inches(0.25)
    p.paragraph_format.right_indent = Inches(0.25)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(code.rstrip())
    run.font.name = "Consolas"
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(40, 45, 50)
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), "F1F4F2")
    p._p.get_or_add_pPr().append(shading)


def parse_markdown(doc: Document, lines: list[str]) -> None:
    index = 0
    in_code = False
    code_lines: list[str] = []
    while index < len(lines):
        line = lines[index].rstrip("\n")
        if line.startswith("```"):
            if in_code:
                add_code(doc, "\n".join(code_lines))
                code_lines = []
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if not line.strip():
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            level = min(len(heading.group(1)), 3)
            doc.add_heading(heading.group(2).strip(), level=level)
            index += 1
            continue
        if line.startswith(">"):
            p = doc.add_paragraph(style="Intense Quote")
            p.add_run(line.lstrip("> ").strip())
            index += 1
            continue
        if line.startswith("- ") or line.startswith("* "):
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(line[2:].strip())
            index += 1
            continue
        if re.match(r"^\d+\.\s+", line):
            p = doc.add_paragraph(style="List Number")
            p.add_run(re.sub(r"^\d+\.\s+", "", line))
            index += 1
            continue
        if line.startswith("|") and index + 1 < len(lines) and lines[index + 1].lstrip().startswith("|---"):
            headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
            rows: list[list[str]] = []
            index += 2
            while index < len(lines) and lines[index].startswith("|"):
                rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            table = doc.add_table(rows=1, cols=len(headers))
            table.style = "Light Shading Accent 1"
            for col, value in enumerate(headers):
                set_cell_text(table.rows[0].cells[col], value)
            for row in rows:
                cells = table.add_row().cells
                for col in range(len(headers)):
                    set_cell_text(cells[col], row[col] if col < len(row) else "")
            doc.add_paragraph()
            continue
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        p.add_run(line)
        index += 1


def build() -> None:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)
    styles = doc.styles
    styles["Normal"].font.name = "Microsoft YaHei"
    styles["Normal"].font.size = Pt(10.5)
    for name, size, color in (("Title", 28, "19352F"), ("Heading 1", 20, "304B3D"), ("Heading 2", 15, "3F6B55"), ("Heading 3", 12, "4D6C5B")):
        style = styles[name]
        style.font.name = "Microsoft YaHei"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)

    footer = section.footer.paragraphs[0]
    add_page_number(footer)

    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run("EduMatrix 智教矩阵\n完整技术文档")
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.add_run("软件杯 A3：基于大模型的个性化资源生成与学习多智能体系统研发").bold = True
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run("版本：2026-07-19  |  默认验收模式：无 Docker  |  数据状态：事实/合成明确标注")
    doc.add_paragraph()
    note = doc.add_paragraph(style="Intense Quote")
    note.add_run("本文件由当前源码、测试命令、运行时安全矩阵和无 Docker 浏览器验收证据生成；打开后请更新目录字段。")
    doc.add_page_break()
    doc.add_heading("目录", level=1)
    add_toc(doc.add_paragraph())
    doc.add_page_break()

    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    parse_markdown(doc, lines)

    doc.add_page_break()
    doc.add_heading("附录：浏览器验收截图", level=1)
    for filename, caption in (("02-dashboard.png", "图 A-1：无 Docker 模式下的学习仪表盘"), ("04-chat-response.png", "图 A-2：多智能体对话、Timeline 与双曲可视化"), ("05-code-sandbox-disabled.png", "图 A-3：代码沙箱作为可选能力明确未启用"), ("06-learning-path.png", "图 A-4：A* 学习路径与掌握状态")):
        path = SCREENSHOTS / filename
        if path.exists():
            doc.add_picture(str(path), width=Inches(6.7))
            p = doc.add_paragraph(caption)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.runs[0].italic = True

    doc.save(OUTPUT)
    print(f"created: {OUTPUT}")


if __name__ == "__main__":
    build()

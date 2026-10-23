from pathlib import Path
import json
import re
import zipfile

from pypdf import PdfReader


BASE = Path(__file__).resolve().parents[1] / "outputs" / "competition_submission_rebuild"


def main() -> None:
    print("PDF_PAGES")
    pages = {}
    for path in sorted((BASE / "pdf").glob("*.pdf")):
        pages[path.name] = len(PdfReader(str(path)).pages)
        print(path.name, pages[path.name])

    print("DOCX_CHECK")
    checks = {}
    for path in sorted((BASE / "documents").glob("*.docx")):
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
            footer_names = [name for name in archive.namelist() if name.startswith("word/footer") and name.endswith(".xml")]
            footer = "".join(archive.read(name).decode("utf-8") for name in footer_names)
        item = {
            "headings": len(re.findall(r"<w:pStyle[^>]+w:val=\"Heading", xml)),
            "chapter_headings": len(re.findall(r"^# (?:[0-9]+[.]|摘要|场景与问题|当前领域范围|总体架构|业务闭环|画像模型|资源与决策|可靠性、安全和限制)", (BASE / "documents" / path.name.replace(".docx", ".md")).read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)) if path.name.startswith("01_") else 0,
            "tables": len(re.findall(r"<w:tbl>", xml)),
            "pictures": len(re.findall(r"<w:drawing>", xml)),
            "captions": len(re.findall(r"图 [0-9]+：", xml)),
            "page_fields": len(re.findall(r"<w:instrText[^>]*>PAGE</w:instrText>", footer)),
            "toc_field": "TOC" in xml,
        }
        checks[path.name] = item
        print(path.name, item)

    old_tokens = ["00015352"]
    secret_patterns = [r"sk-[A-Za-z0-9]{20,}", r"AKIA[0-9A-Z]{16}", r"eyJ[A-Za-z0-9_-]{20,}"]
    scan_files = [p for p in BASE.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".json", ".jsonl", ".csv", ".txt"} and "knowledge_base" not in p.parts and not any(part.startswith("current_evaluation_") for part in p.parts)]
    hits = []
    for path in scan_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in old_tokens:
            if token in text:
                hits.append({"file": str(path.relative_to(BASE)), "token": token})
        for pattern in secret_patterns:
            if re.search(pattern, text):
                hits.append({"file": str(path.relative_to(BASE)), "token": pattern})
    forbidden_suffixes = {".env", ".db", ".sqlite", ".sqlite3", ".wal", ".shm"}
    forbidden = [str(p.relative_to(BASE)) for p in BASE.rglob("*") if p.is_file() and p.suffix.lower() in forbidden_suffixes]
    print("SCAN", json.dumps({"old_or_secret_hits": hits, "forbidden_runtime_files": forbidden}, ensure_ascii=False))
    print("GATES", json.dumps({
        "main_pdf_pages_50_70": 50 <= pages.get("01_作品设计与实现方案.pdf", 0) <= 70,
        "main_chapter_headings_12_18": 12 <= checks.get("01_作品设计与实现方案.docx", {}).get("chapter_headings", 0) <= 18,
        "main_tables_20_plus": checks.get("01_作品设计与实现方案.docx", {}).get("tables", 0) >= 20,
        "main_figures_15_plus": checks.get("01_作品设计与实现方案.docx", {}).get("pictures", 0) >= 15,
        "main_captions_15_plus": checks.get("01_作品设计与实现方案.docx", {}).get("captions", 0) >= 15,
        "main_page_field": checks.get("01_作品设计与实现方案.docx", {}).get("page_fields", 0) >= 1,
        "main_toc": checks.get("01_作品设计与实现方案.docx", {}).get("toc_field", False),
        "no_scan_hits": not hits and not forbidden,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

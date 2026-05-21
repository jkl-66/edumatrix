"""
EduMatrix Data Classifier
Scans all downloaded data and classifies files into categories.
"""
import json
from pathlib import Path
from collections import Counter, defaultdict

BASE = Path(r"d:\code\edumatrix")
DATA = BASE / "data"

CATEGORY_RULES = [
    ("pdf", [".pdf"]),
    ("ppt_slides", [".pptx", ".ppt"]),
    ("code_python", [".py"]),
    ("notebook", [".ipynb"]),
    ("textbook_markdown", [".md", ".rst", ".tex"]),
    ("dataset_csv", [".csv", ".data", ".arff"]),
    ("course_page_html", [".html", ".htm"]),
    ("image", [".png", ".jpg", ".jpeg", ".gif", ".svg"]),
    ("ebook", [".epub"]),
    ("config", [".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"]),
    ("data_other", [".txt", ".tsv", ".jsonl"]),
]

def classify_file(ext: str) -> str:
    for cat, exts in CATEGORY_RULES:
        if ext.lower() in exts:
            return cat
    return "other"

results = defaultdict(list)
total_size = 0
by_category = Counter()
by_repo = Counter()

for fpath in DATA.rglob("*"):
    if not fpath.is_file():
        continue
    rel = fpath.relative_to(BASE)
    ext = fpath.suffix
    cat = classify_file(ext)
    size = fpath.stat().st_size
    total_size += size
    by_category[cat] += 1

    # Identify repo source from path
    repo = ""
    parts = fpath.relative_to(DATA).parts
    if len(parts) >= 3 and parts[0] == "raw" and parts[1] == "github_repos":
        repo = parts[2]
    elif len(parts) >= 2 and parts[0] == "datasets":
        repo = "dataset"
    elif len(parts) >= 2 and parts[0] == "raw" and parts[1] == "course_pages":
        repo = "course_pages"

    by_repo[repo] += 1

    results[cat].append({
        "path": str(rel),
        "size_bytes": size,
        "repo": repo,
    })

# Print report
print("=" * 80)
print("DATA CLASSIFICATION REPORT")
print("=" * 80)
print(f"\nTotal files: {sum(by_category.values())}")
print(f"Total size: {total_size / 1024 / 1024:.2f} MiB\n")

print("By Category:")
for cat in sorted(by_category.keys()):
    items = results[cat]
    size_mb = sum(i["size_bytes"] for i in items) / 1024 / 1024
    print(f"  {cat:25s} : {by_category[cat]:5d} files, {size_mb:8.2f} MiB")

print("\nBy Source:")
for repo in sorted(by_repo.keys()):
    rname = repo if repo else "(root)"
    print(f"  {rname:40s} : {by_repo[repo]:5d} files")

# Save JSON report
report_path = BASE / "data" / "manifest" / "data_classification.json"
with open(report_path, "w", encoding="utf-8") as f:
    json.dump({
        "total_files": sum(by_category.values()),
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "by_category": {k: {"count": v, "files": results[k]} for k, v in sorted(by_category.items())},
        "by_source": dict(by_repo.most_common()),
    }, f, ensure_ascii=False, indent=2)

print(f"\nFull report saved to {report_path}")

# Save a simplified manifest for ingestion
ingest_list = []
for cat, items in results.items():
    ingest_list.append({
        "category": cat,
        "files": sorted(items, key=lambda x: x["path"])
    })
ingest_path = BASE / "data" / "manifest" / "ingestion_manifest.json"
with open(ingest_path, "w", encoding="utf-8") as f:
    json.dump(ingest_list, f, ensure_ascii=False, indent=2)
print(f"Ingestion manifest saved to {ingest_path}")

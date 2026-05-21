from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable
from urllib.request import urlretrieve


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


@dataclass(frozen=True)
class Source:
    key: str
    url: str
    kind: str
    asset_type: str
    topics: tuple[str, ...]
    language: str
    redistribution_policy: str
    notes: str


@dataclass(frozen=True)
class VideoNode:
    source_key: str
    title: str
    url: str
    platform: str
    course_node: str
    text_nodes: tuple[str, ...]
    expected_modalities: tuple[str, ...]
    usage: str


SOURCES: tuple[Source, ...] = (
    Source(
        "machine-learning-refined",
        "https://github.com/neonwatty/machine-learning-refined.git",
        "git",
        "pdf,pptx,ipynb,py",
        ("linear_regression", "logistic_regression", "optimization", "neural_networks", "visualization"),
        "en",
        "local_test_only_check_repo_license",
        "Book PDFs, chapter PDFs, PPTX slides, notebooks and exercises.",
    ),
    Source(
        "compsci-589",
        "https://github.com/mlds-lab/COMPSCI-589.git",
        "git",
        "pdf,tex,ipynb,py",
        ("regression", "classification", "clustering", "dimensionality_reduction", "evaluation"),
        "en",
        "GPL-3.0",
        "Open applied ML course with slides, handouts and demos.",
    ),
    Source(
        "mlcourse-ai",
        "https://github.com/Yorko/mlcourse.ai.git",
        "git",
        "ipynb,md,images,data",
        ("pandas", "visualization", "trees", "logistic_regression", "ensembles", "pca", "clustering"),
        "en,zh",
        "CC-BY-NC-SA-4.0_check_bonus_restrictions",
        "Practice-heavy course with notebooks, images, Chinese materials and links.",
    ),
    Source(
        "mlbook-dafriedman",
        "https://github.com/dafriedman97/mlbook.git",
        "git",
        "pdf,ipynb,py",
        ("linear_regression", "logistic_regression", "naive_bayes", "trees", "ensembles", "neural_networks"),
        "en",
        "CC-BY-NC-SA",
        "Machine Learning from Scratch book and examples.",
    ),
    Source(
        "data-science-from-scratch",
        "https://github.com/joelgrus/data-science-from-scratch.git",
        "git",
        "py",
        ("linear_algebra", "statistics", "gradient_descent", "classification", "clustering"),
        "en",
        "MIT",
        "Pure Python teaching code.",
    ),
    Source(
        "nyandwi-machine-learning-complete",
        "https://github.com/Nyandwi/machine_learning_complete.git",
        "git",
        "ipynb,images",
        ("python", "numpy", "pandas", "visualization", "classical_ml", "deep_learning"),
        "en",
        "MIT",
        "Beginner-friendly notebooks and visuals.",
    ),
    Source(
        "pumpkin-book",
        "https://github.com/datawhalechina/pumpkin-book.git",
        "git",
        "pdf,md,images",
        ("watermelon_book", "formula_derivation", "linear_model", "decision_tree", "svm", "ensemble"),
        "zh",
        "check_repo_license",
        "Open companion formula derivations for 周志华《机器学习》.",
    ),
    Source(
        "vay-keen-watermelon-notes",
        "https://github.com/Vay-keen/Machine-learning-learning-notes.git",
        "git",
        "md,images",
        ("watermelon_book", "chinese_notes", "classification", "trees", "svm", "bayes"),
        "zh",
        "local_test_only_check_repo_license",
        "Chinese notes aligned to 西瓜书 chapters.",
    ),
    Source(
        "watermelonbook-training",
        "https://github.com/relph1119/machinelearning-watermelonbook.git",
        "git",
        "ipynb,md,py",
        ("watermelon_book", "notebooks", "training_camp"),
        "zh",
        "local_test_only_check_repo_license",
        "西瓜书 training materials and notebooks.",
    ),
    Source(
        "dtreeviz",
        "https://github.com/parrt/dtreeviz.git",
        "git",
        "py,ipynb,images",
        ("decision_tree", "visualization", "iris", "interpretability"),
        "en",
        "MIT",
        "Decision tree visualization and interpretation.",
    ),
    Source(
        "edge-impulse-courseware",
        "https://github.com/edgeimpulse/courseware-embedded-machine-learning.git",
        "git",
        "slides,md,notebooks,video_metadata",
        ("embedded_ml", "tinyml", "applications"),
        "en",
        "check_repo_license",
        "Applied ML and TinyML courseware.",
    ),
    Source(
        "rasbt-ml-book-code",
        "https://github.com/rasbt/machine-learning-book.git",
        "git",
        "ipynb,py",
        ("sklearn", "pytorch", "classification", "evaluation", "deep_learning"),
        "en",
        "code_repo_for_commercial_book_check_license",
        "High-quality code examples for scikit-learn and PyTorch.",
    ),
    Source(
        "ruban-iris-classification",
        "https://github.com/Ruban2205/Iris_Classification.git",
        "git",
        "ipynb,pdf,csv,streamlit",
        ("iris", "classification", "visualization", "student_project"),
        "en",
        "MIT",
        "Simple end-to-end Iris classification project.",
    ),
    Source(
        "uci-iris",
        "https://archive.ics.uci.edu/static/public/53/iris.zip",
        "direct",
        "zip,csv,metadata",
        ("iris", "classification", "dataset"),
        "en",
        "UCI_dataset_terms",
        "Canonical Iris dataset.",
    ),
    Source(
        "sklearn-iris-decision-surface",
        "https://scikit-learn.org/stable/_downloads/1935e293d69b820c51b298c649c34b39/plot_iris_dtc.py",
        "direct",
        "py",
        ("iris", "decision_tree", "decision_boundary", "visualization"),
        "en",
        "BSD-3-Clause_sklearn",
        "Decision tree decision surface example over Iris feature pairs.",
    ),
)


VIDEOS: tuple[VideoNode, ...] = (
    VideoNode(
        "ml-engineering-course-videos",
        "ML Engineering course video index",
        "https://ml-course.github.io/master/",
        "course_page/youtube_links",
        "machine_learning_project_pipeline",
        ("data_preprocessing", "model_training", "evaluation", "deployment_awareness"),
        ("video_url", "slides", "notebook"),
        "Store URL/title/lesson node only; fetch transcript lazily if terms allow.",
    ),
    VideoNode(
        "mlcourse-ai-videos",
        "mlcourse.ai video and slide links",
        "https://github.com/Yorko/mlcourse.ai",
        "youtube/course_page",
        "classical_ml_practice",
        ("eda", "visualization", "decision_tree", "logistic_regression", "ensembles", "clustering"),
        ("video_url", "notebook", "slides"),
        "Align each video to matching notebook lesson.",
    ),
    VideoNode(
        "vu-ml-videos",
        "Machine Learning @ VU lecture videos",
        "https://mlvu.github.io/",
        "course_page/video_links",
        "introductory_ml_theory",
        ("linear_models", "probabilistic_models", "trees", "neural_networks", "evaluation"),
        ("video_url", "pdf_slides", "worksheet"),
        "Use course node as anchor and store lecture page metadata.",
    ),
    VideoNode(
        "uva-ml1-videos",
        "UvA Machine Learning 1 lectures",
        "https://uvaml1.github.io/",
        "course_page/video_links",
        "prml_style_ml",
        ("linear_regression", "classification", "bayes", "kernel_methods", "clustering"),
        ("video_url", "pdf_slides"),
        "Public lecture page; store metadata only unless license allows transcript.",
    ),
    VideoNode(
        "lmu-iml-videos",
        "LMU Interpretable Machine Learning videos",
        "https://slds-lmu.github.io/iml/",
        "course_page/video_links",
        "interpretability_and_teacher_dashboard",
        ("feature_importance", "pdp", "shap", "model_explanation", "evaluation_errors"),
        ("video_url", "pdf_slides", "exercise"),
        "Good teacher-side explainability nodes.",
    ),
    VideoNode(
        "bilibili-watermelon-book-reference",
        "Bilibili 西瓜书 lecture playlist metadata",
        "https://www.bilibili.com/video/BV1ks2bYGETs/",
        "bilibili",
        "watermelon_book_reference",
        ("decision_tree", "bayes", "linear_model", "svm", "ensemble", "clustering"),
        ("video_url", "topic_metadata"),
        "Metadata only. Do not mirror video by default.",
    ),
)


ASSET_EXTENSIONS = {".pdf", ".ppt", ".pptx", ".ipynb", ".py", ".md", ".csv", ".png", ".jpg", ".jpeg", ".svg"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect local-test multimodal ML teaching data into data/.")
    parser.add_argument("--download", action="store_true", help="Actually download/clone sources. Without this, only manifests are written.")
    parser.add_argument("--limit", type=int, default=0, help="Limit source count for smoke tests.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing direct files and reclone git repos.")
    args = parser.parse_args()

    ensure_dirs()
    selected = SOURCES[: args.limit] if args.limit else SOURCES
    write_source_manifest(selected)
    write_video_manifest(VIDEOS)
    write_node_alignment(selected, VIDEOS)

    if not args.download:
        print("Wrote manifests only. Re-run with --download to fetch assets.")
        return 0

    for source in selected:
        try:
            if source.kind == "git":
                clone_source(source, force=args.force)
            elif source.kind == "direct":
                download_source(source, force=args.force)
        except Exception as exc:
            append_event({"event": "download_error", "source": source.key, "error": str(exc)})
            print(f"[error] {source.key}: {exc}", file=sys.stderr)

    write_asset_inventory()
    print(f"Done. Data stored under {DATA}")
    return 0


def ensure_dirs() -> None:
    for folder in (
        DATA / "raw" / "github_repos",
        DATA / "raw" / "direct_assets",
        DATA / "raw" / "videos_metadata",
        DATA / "manifest",
    ):
        folder.mkdir(parents=True, exist_ok=True)


def write_source_manifest(sources: Iterable[Source]) -> None:
    path = DATA / "manifest" / "source_manifest.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for source in sources:
            handle.write(json.dumps(asdict(source), ensure_ascii=False) + "\n")


def write_video_manifest(videos: Iterable[VideoNode]) -> None:
    path = DATA / "raw" / "videos_metadata" / "video_node_alignment.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for video in videos:
            handle.write(json.dumps(asdict(video), ensure_ascii=False) + "\n")


def write_node_alignment(sources: Iterable[Source], videos: Iterable[VideoNode]) -> None:
    path = DATA / "manifest" / "node_alignment.csv"
    rows = []
    for source in sources:
        for topic in source.topics:
            rows.append((topic, source.key, source.asset_type, "source_asset", source.url))
    for video in videos:
        for node in video.text_nodes:
            rows.append((node, video.source_key, ",".join(video.expected_modalities), "video_metadata", video.url))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("course_node", "source_key", "modalities", "alignment_type", "url"))
        writer.writerows(rows)


def clone_source(source: Source, *, force: bool) -> None:
    target = DATA / "raw" / "github_repos" / source.key
    if target.exists() and force:
        shutil.rmtree(target)
    if target.exists():
        append_event({"event": "skip_existing_repo", "source": source.key, "path": str(target)})
        return
    subprocess.run(["git", "clone", "--depth", "1", source.url, str(target)], check=True)
    append_event({"event": "cloned_repo", "source": source.key, "path": str(target)})


def download_source(source: Source, *, force: bool) -> None:
    suffix = Path(source.url.split("?")[0]).suffix or ".asset"
    target = DATA / "raw" / "direct_assets" / f"{source.key}{suffix}"
    if target.exists() and not force:
        append_event({"event": "skip_existing_direct_asset", "source": source.key, "path": str(target)})
        return
    urlretrieve(source.url, target)
    append_event({"event": "downloaded_direct_asset", "source": source.key, "path": str(target)})


def write_asset_inventory() -> None:
    path = DATA / "manifest" / "asset_inventory.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for file_path in DATA.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in ASSET_EXTENSIONS:
                continue
            record = {
                "local_path": str(file_path.relative_to(ROOT)),
                "asset_type": file_path.suffix.lower().lstrip("."),
                "size_bytes": file_path.stat().st_size,
                "indexed": False,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_event(record: dict[str, object]) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        **record,
    }
    path = DATA / "manifest" / "collection_events.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

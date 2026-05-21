"""
Generate comprehensive manifest JSONL for all downloaded assets
"""
import json
from pathlib import Path

BASE = Path(r"d:\code\edumatrix")
MANIFEST_DIR = BASE / "data" / "manifest"
MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
manifest_path = MANIFEST_DIR / "full_manifest.jsonl"

entries = []

# ==========================================
# 1. Datasets
# ==========================================
dataset_info = [
    {
        "name": "iris",
        "source_url": "https://archive.ics.uci.edu/dataset/53/iris",
        "license": "BSD-3-Clause (scikit-learn)",
        "local_path": "data/datasets/iris/iris.csv",
        "rows": 150, "cols": 5,
        "tags": ["classification", "iris", "scikit-learn"]
    },
    {
        "name": "wine",
        "source_url": "https://archive.ics.uci.edu/dataset/109/wine",
        "license": "CC BY 4.0",
        "local_path": "data/datasets/wine/wine.csv",
        "rows": 178, "cols": 14,
        "tags": ["classification", "multiclass", "uci"]
    },
    {
        "name": "breast_cancer_wisconsin",
        "source_url": "https://archive.ics.uci.edu/dataset/17/breast+cancer+wisconsin+diagnostic",
        "license": "CC BY 4.0",
        "local_path": "data/datasets/breast_cancer_wisconsin/breast_cancer_wisconsin.csv",
        "rows": 569, "cols": 32,
        "tags": ["classification", "binary", "uci", "evaluation"]
    },
    {
        "name": "adult",
        "source_url": "https://archive.ics.uci.edu/dataset/2/adult",
        "license": "CC BY 4.0",
        "local_path": "data/datasets/adult/adult.csv",
        "rows": 48842, "cols": 15,
        "tags": ["classification", "binary", "uci", "fairness", "ethics"]
    },
    {
        "name": "auto_mpg",
        "source_url": "https://archive.ics.uci.edu/dataset/9/auto+mpg",
        "license": "CC BY 4.0",
        "local_path": "data/datasets/auto_mpg/auto_mpg.csv",
        "rows": 398, "cols": 9,
        "tags": ["regression", "uci", "missing_values", "feature_engineering"]
    },
    {
        "name": "diabetes",
        "source_url": "https://scikit-learn.org/stable/datasets/toy_dataset.html#diabetes-dataset",
        "license": "BSD-3-Clause",
        "local_path": "data/datasets/diabetes/diabetes.csv",
        "rows": 442, "cols": 11,
        "tags": ["regression", "scikit-learn", "linear_model"]
    },
    {
        "name": "california_housing",
        "source_url": "https://scikit-learn.org/stable/modules/generated/sklearn.datasets.fetch_california_housing.html",
        "license": "BSD-3-Clause",
        "local_path": "data/datasets/california_housing/california_housing.csv",
        "rows": 20640, "cols": 9,
        "tags": ["regression", "scikit-learn", "housing", "generalization"]
    },
    {
        "name": "mnist_784",
        "source_url": "https://www.openml.org/d/554",
        "license": "Public Domain (CC0)",
        "local_path": "data/datasets/mnist_784/mnist_784.csv",
        "rows": 70000, "cols": 785,
        "tags": ["classification", "image", "openml", "neural_networks"]
    }
]

for ds in dataset_info:
    entries.append({
        "source_url": ds["source_url"],
        "repo": "",
        "license": ds["license"],
        "asset_type": "dataset",
        "dataset_name": ds["name"],
        "local_path": ds["local_path"],
        "rows": ds["rows"],
        "columns": ds["cols"],
        "topic_tags": ds["tags"],
        "language": "",
        "redistribution_policy": "open",
        "ingestion_status": "downloaded"
    })

# ==========================================
# 2. GitHub Repositories
# ==========================================
repo_info = [
    {
        "repo": "neonwatty/machine-learning-refined",
        "url": "https://github.com/neonwatty/machine-learning-refined",
        "license": "MIT (per README)",
        "local_path": "data/raw/github_repos/machine-learning-refined",
        "size_mb": 109,
        "asset_types": ["pdf", "pptx", "ipynb", "py"],
        "tags": ["linear_regression", "logistic_regression", "regularization", "neural_networks", "visualization"],
        "language": "en"
    },
    {
        "repo": "mlds-lab/COMPSCI-589",
        "url": "https://github.com/mlds-lab/COMPSCI-589",
        "license": "GPL-3.0",
        "local_path": "data/raw/github_repos/COMPSCI-589",
        "size_mb": 99,
        "asset_types": ["pdf", "ipynb", "py", "tex"],
        "tags": ["regression", "classification", "clustering", "dimensionality_reduction"],
        "language": "en"
    },
    {
        "repo": "Yorko/mlcourse.ai",
        "url": "https://github.com/Yorko/mlcourse.ai",
        "license": "CC BY-NC-SA 4.0",
        "local_path": "data/raw/github_repos/mlcourse.ai",
        "size_mb": 192,
        "asset_types": ["ipynb", "py", "csv", "png"],
        "tags": ["pandas", "visualization", "trees", "logistic_regression", "ensembles", "pca", "clustering"],
        "language": "en"
    },
    {
        "repo": "dafriedman97/mlbook",
        "url": "https://github.com/dafriedman97/mlbook",
        "license": "CC BY-NC-SA",
        "local_path": "data/raw/github_repos/mlbook",
        "size_mb": 23,
        "asset_types": ["pdf", "epub", "py"],
        "tags": ["ols", "logistic_regression", "naive_bayes", "trees", "ensembles", "neural_nets"],
        "language": "en"
    },
    {
        "repo": "Nyandwi/machine_learning_complete",
        "url": "https://github.com/Nyandwi/machine_learning_complete",
        "license": "MIT",
        "local_path": "data/raw/github_repos/machine_learning_complete",
        "size_mb": 129,
        "asset_types": ["ipynb", "png"],
        "tags": ["python", "numpy", "pandas", "visualization", "classification", "regression", "cv", "nlp"],
        "language": "en"
    },
    {
        "repo": "datawhalechina/pumpkin-book",
        "url": "https://github.com/datawhalechina/pumpkin-book",
        "license": "Apache-2.0",
        "local_path": "data/raw/github_repos/pumpkin-book",
        "size_mb": 7,
        "asset_types": ["pdf", "md", "ipynb"],
        "tags": ["watermelon_book", "formula_derivation", "chinese", "theory"],
        "language": "zh"
    }
]

for repo in repo_info:
    entries.append({
        "source_url": repo["url"],
        "repo": repo["repo"],
        "license": repo["license"],
        "asset_type": "github_repo",
        "dataset_name": "",
        "local_path": repo["local_path"],
        "size_mb": repo["size_mb"],
        "contained_asset_types": repo["asset_types"],
        "topic_tags": repo["tags"],
        "language": repo["language"],
        "redistribution_policy": "check_license",
        "ingestion_status": "cloned"
    })

# ==========================================
# 3. Course Pages
# ==========================================
course_pages = [
    {
        "source_url": "https://scikit-learn.org/stable/auto_examples/tree/plot_iris_dtc.html",
        "local_path": "data/raw/course_pages/sklearn_iris_dtc.html",
        "tags": ["iris", "decision_tree", "visualization"],
        "language": "en"
    },
    {
        "source_url": "https://ml-course.github.io/master/",
        "local_path": "data/raw/course_pages/ml_engineering_index.html",
        "tags": ["ml_engineering", "course"],
        "language": "en"
    }
]

for cp in course_pages:
    p = BASE / cp["local_path"]
    if p.exists():
        entries.append({
            "source_url": cp["source_url"],
            "repo": "",
            "license": "",
            "asset_type": "course_page",
            "dataset_name": "",
            "local_path": cp["local_path"],
            "size_bytes": p.stat().st_size,
            "topic_tags": cp["tags"],
            "language": cp["language"],
            "redistribution_policy": "open_access",
            "ingestion_status": "downloaded"
        })

# ==========================================
# Write manifest
# ==========================================
with open(manifest_path, "w", encoding="utf-8") as f:
    for entry in entries:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

print(f"Manifest written to {manifest_path}")
print(f"Total entries: {len(entries)}")

# Print summary
from collections import Counter
types = Counter(e["asset_type"] for e in entries)
print(f"\nManifest summary by type:")
for t, c in types.most_common():
    print(f"  {t}: {c}")

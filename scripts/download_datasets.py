"""
EduMatrix Dataset Downloader
Downloads all datasets listed in machine_learning_course_datasets.md
"""
import os
import json
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(r"d:\code\edumatrix\data\datasets")
DATA_DIR.mkdir(parents=True, exist_ok=True)

manifest = []

def save_csv(df, name, subdir="", metadata=None):
    dir_path = DATA_DIR / subdir / name
    dir_path.mkdir(parents=True, exist_ok=True)
    csv_path = dir_path / f"{name}.csv"
    df.to_csv(csv_path, index=False)
    print(f"  [OK] Saved {csv_path} ({len(df)} rows, {len(df.columns)} cols)")

    entry = {
        "source_url": metadata.get("source_url", ""),
        "dataset_name": name,
        "asset_type": "dataset",
        "license": metadata.get("license", ""),
        "local_path": str(csv_path.relative_to(Path(r"d:\code\edumatrix"))),
        "rows": len(df),
        "columns": len(df.columns),
        "topic_tags": metadata.get("tags", []),
        "ingestion_status": "downloaded"
    }
    manifest.append(entry)

# ============================================================
# 1. Iris - UCI (ucimlrepo)
# ============================================================
print("=" * 60)
print("1. Iris (UCI)")
try:
    from ucimlrepo import fetch_ucirepo
    iris = fetch_ucirepo(id=53)
    df_iris = iris.data.original
    if df_iris is None:
        df_iris = pd.concat([iris.data.features, iris.data.targets], axis=1)
    save_csv(df_iris, "iris", metadata={
        "source_url": "https://archive.ics.uci.edu/dataset/53/iris",
        "license": "CC BY 4.0",
        "tags": ["classification", "iris", "uci"]
    })
except Exception as e:
    print(f"  [FAIL] ucimlrepo iris: {e}")
    print("  Trying direct download...")
    import requests
    url = "https://archive.ics.uci.edu/static/public/53/iris.csv"
    resp = requests.get(url)
    if resp.status_code == 200:
        with open("iris.csv", "wb") as f:
            f.write(resp.content)
        df_iris = pd.read_csv("iris.csv")
        save_csv(df_iris, "iris", metadata={
            "source_url": "https://archive.ics.uci.edu/dataset/53/iris",
            "license": "CC BY 4.0",
            "tags": ["classification", "iris", "uci"]
        })
        os.remove("iris.csv")
    else:
        print(f"  [FAIL] direct download also failed: {resp.status_code}")

# ============================================================
# 2. Wine - UCI
# ============================================================
print("\n" + "=" * 60)
print("2. Wine (UCI)")
try:
    wine = fetch_ucirepo(id=109)
    df_wine = wine.data.original
    if df_wine is None:
        df_wine = pd.concat([wine.data.features, wine.data.targets], axis=1)
    save_csv(df_wine, "wine", metadata={
        "source_url": "https://archive.ics.uci.edu/dataset/109/wine",
        "license": "CC BY 4.0",
        "tags": ["classification", "multiclass", "uci"]
    })
except Exception as e:
    print(f"  [FAIL] ucimlrepo wine: {e}")

# ============================================================
# 3. Breast Cancer Wisconsin Diagnostic - UCI
# ============================================================
print("\n" + "=" * 60)
print("3. Breast Cancer Wisconsin Diagnostic (UCI)")
try:
    bc = fetch_ucirepo(id=17)
    df_bc = bc.data.original
    if df_bc is None:
        df_bc = pd.concat([bc.data.features, bc.data.targets], axis=1)
    save_csv(df_bc, "breast_cancer_wisconsin", metadata={
        "source_url": "https://archive.ics.uci.edu/dataset/17/breast+cancer+wisconsin+diagnostic",
        "license": "CC BY 4.0",
        "tags": ["classification", "binary", "uci", "evaluation"]
    })
except Exception as e:
    print(f"  [FAIL] ucimlrepo breast cancer: {e}")

# ============================================================
# 4. Adult - UCI
# ============================================================
print("\n" + "=" * 60)
print("4. Adult Income (UCI)")
try:
    adult = fetch_ucirepo(id=2)
    df_adult = adult.data.original
    if df_adult is None:
        df_adult = pd.concat([adult.data.features, adult.data.targets], axis=1)
    save_csv(df_adult, "adult", metadata={
        "source_url": "https://archive.ics.uci.edu/dataset/2/adult",
        "license": "CC BY 4.0",
        "tags": ["classification", "binary", "uci", "fairness", "ethics"]
    })
except Exception as e:
    print(f"  [FAIL] ucimlrepo adult: {e}")

# ============================================================
# 5. Auto MPG - UCI
# ============================================================
print("\n" + "=" * 60)
print("5. Auto MPG (UCI)")
try:
    mpg = fetch_ucirepo(id=9)
    df_mpg = mpg.data.original
    if df_mpg is None:
        df_mpg = pd.concat([mpg.data.features, mpg.data.targets], axis=1)
    save_csv(df_mpg, "auto_mpg", metadata={
        "source_url": "https://archive.ics.uci.edu/dataset/9/auto+mpg",
        "license": "CC BY 4.0",
        "tags": ["regression", "uci", "missing_values", "feature_engineering"]
    })
except Exception as e:
    print(f"  [FAIL] ucimlrepo auto_mpg: {e}")

# ============================================================
# 6. Diabetes - scikit-learn built-in
# ============================================================
print("\n" + "=" * 60)
print("6. Diabetes (scikit-learn)")
from sklearn.datasets import load_diabetes
diabetes = load_diabetes(as_frame=True)
df_diabetes = diabetes.frame
save_csv(df_diabetes, "diabetes", metadata={
    "source_url": "https://scikit-learn.org/stable/datasets/toy_dataset.html#diabetes-dataset",
    "license": "BSD-3-Clause",
    "tags": ["regression", "scikit-learn", "linear_model"]
})

# ============================================================
# 7. California Housing - scikit-learn
# ============================================================
print("\n" + "=" * 60)
print("7. California Housing (scikit-learn)")
from sklearn.datasets import fetch_california_housing
housing = fetch_california_housing(as_frame=True)
df_housing = housing.frame
save_csv(df_housing, "california_housing", metadata={
    "source_url": "https://scikit-learn.org/stable/modules/generated/sklearn.datasets.fetch_california_housing.html",
    "license": "BSD-3-Clause",
    "tags": ["regression", "scikit-learn", "housing", "generalization"]
})

# ============================================================
# 8. MNIST 784 - OpenML
# ============================================================
print("\n" + "=" * 60)
print("8. MNIST 784 (OpenML)")
try:
    import openml
    mnist = openml.datasets.get_dataset(554)
    X_mnist, y_mnist, _, _ = mnist.get_data(target=mnist.default_target_attribute)
    df_mnist = X_mnist.copy()
    df_mnist["class"] = y_mnist
    save_csv(df_mnist, "mnist_784", metadata={
        "source_url": "https://www.openml.org/d/554",
        "license": "Public Domain (CC0)",
        "tags": ["classification", "image", "openml", "neural_networks"]
    })
except Exception as e:
    print(f"  [FAIL] openml mnist: {e}")
    print("  Trying direct download from OpenML...")
    try:
        url = "https://www.openml.org/data/get_csv/554"
        df_mnist = pd.read_csv(url)
        save_csv(df_mnist, "mnist_784", metadata={
            "source_url": "https://www.openml.org/d/554",
            "license": "Public Domain (CC0)",
            "tags": ["classification", "image", "openml", "neural_networks"]
        })
    except Exception as e2:
        print(f"  [FAIL] direct mnist download: {e2}")

# ============================================================
# Save manifest
# ============================================================
print("\n" + "=" * 60)
manifest_path = Path(r"d:\code\edumatrix\data\manifest\datasets_manifest.jsonl")
with open(manifest_path, "w", encoding="utf-8") as f:
    for entry in manifest:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
print(f"Manifest saved to {manifest_path}")
print(f"Total datasets downloaded: {len(manifest)}")
print("=" * 60)
print("ALL DATASETS DOWNLOADED SUCCESSFULLY!")

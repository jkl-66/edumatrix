# Machine Learning Multimodal Teaching Data Sources

This list is curated for EduMatrix's "机器学习导论" RAG/VisRAG dataset. Store downloaded assets under `data/`, which is ignored by git.

## Usage Tiers

- **Tier A - ingest first**: open courseware or repositories with clear public teaching intent, PDFs/slides/notebooks/code are easy to index.
- **Tier B - useful with license review**: strong material, but check license, attribution, and redistribution terms before mirroring files.
- **Tier C - reference only**: copyrighted books/videos or mirrors where we should store only links/metadata, not raw files.

## Priority Sources

| Tier | Source | URL | Modalities | Why it fits EduMatrix | Notes |
|---|---|---|---|---|---|
| A | 人工智能基础本地资料 | Local File | PDF讲义, 文本, PPT | 补充课程的基础概念体系 | 已解压存放在 data/人工智能基础/ 目录下 |
| A | ML Engineering course | https://ml-course.github.io/master/ | Notebooks, PDF slides, YouTube videos | Very aligned with introductory ML: linear models, evaluation, ensembles, data engineering, neural networks. | Good first crawl target because notebook/slide/video are parallel views of same lesson. |
| A | mlcourse.ai | https://github.com/Yorko/mlcourse.ai | Notebooks, images, data, Chinese notebooks, videos/slides links | Strong practice-heavy course with pandas, visualization, trees, logistic regression, ensembles, PCA, clustering. | License badge says CC BY-NC-SA 4.0; bonus assignments are not public-shareable. |
| A | COMPSCI 589 open applied ML course | https://github.com/mlds-lab/COMPSCI-589 | PDF slides, PDF handouts, LaTeX source, Jupyter demos | Full open-source applied ML course with regression/classification/clustering/dimensionality reduction. | GPL-3.0; demos are older Python 2 but still useful as teaching artifacts. |
| A | Machine Learning Refined | https://github.com/neonwatty/machine-learning-refined | Book PDFs, chapter PDFs, PPTX slides, notebooks, exercises | Excellent for "intuition + math + implementation from scratch"; includes visual teaching assets. | Prioritize `chapter_pdfs/`, `presentations/`, `notes/`, `exercises/`. |
| A | Machine Learning from Scratch, Daniel Friedman | https://github.com/dafriedman97/mlbook | PDF/ePub/book, code, solutions | Short from-scratch book covering OLS, logistic regression, Naive Bayes, trees, ensembles, neural nets. | CC BY-NC-SA; good for concise code chunks and formula-grounded text. |
| A | Data Science from Scratch code | https://github.com/joelgrus/data-science-from-scratch | Python code | MIT-licensed pure Python examples for math/stats/ML basics. | Use for simple, inspectable code snippets, not as main lecture text. |
| A | Nyandwi Complete ML Package | https://github.com/Nyandwi/machine_learning_complete | Jupyter notebooks, visualizations | 30+ beginner-friendly notebooks across Python, NumPy, pandas, visualization, classical ML, CV/NLP. | MIT license; good for clean notebook chunks. |
| A | scikit-learn examples | https://scikit-learn.org/stable/auto_examples/ | Python examples, notebooks, rendered plots | Canonical teaching examples for Iris, decision boundaries, model evaluation, pipelines. | Use examples and generated figures as high-quality VisRAG material. |
| A | scikit-learn Iris decision surface | https://scikit-learn.org/stable/auto_examples/tree/plot_iris_dtc.html | Python, notebook, plot image | Very good "鸢尾花" teaching example: decision tree surfaces across feature pairs. | Use as first Iris visual/code seed. |
| A | UCI Iris dataset | https://archive.ics.uci.edu/dataset/53/iris | Tabular dataset, metadata | Canonical introductory classification dataset. | Store raw CSV/metadata under `data/datasets/iris/`. |
| A | VU Machine Learning course | https://mlvu.github.io/ | PDF slides, videos, worksheets/notebooks | BSc ML course with intro, linear models, evaluation, probabilistic models, preprocessing, trees, deep learning. | Good for aligned slide-video pairs. |
| A | LMU Interpretable ML course | https://slds-lmu.github.io/iml/ | Lecture videos, PDF slides, exercises, notebooks | Great for model explanation, feature effects, common evaluation errors. | Better for advanced chapters and teacher dashboard explanations. |
| A | ML Visualized | https://gavinkhung.github.io/machine-learning-visualized/ | Jupyter notebooks, generated visualizations | First-principles ML notebooks with visualizations during training/convergence. | Excellent for visual chunks and animations if license permits. |
| A | dtreeviz | https://github.com/parrt/dtreeviz | Code, notebooks, tree visualizations, decision boundaries | Decision tree visualization and interpretation; highly useful for teaching trees. | Check dependency footprint before integrating generated visuals. |
| A | SHAP Iris notebook | https://shap.github.io/shap/notebooks/Iris%20classification%20with%20scikit-learn.html | Notebook, visual explanations | Good for explainability over Iris classification. | Use as IML/teacher-side explainability supplement. |
| B | UvA Machine Learning 1 | https://uvaml1.github.io/ | PDF slides, videos | Strong PRML-style course with lectures/videos. | Public course page; check terms before mirroring. |
| B | Machine Learning @ VU extra resources | https://mlvu.github.io/ | PDF slides, videos, worksheets | Public ML course materials; useful for fundamentals. | Same as above: store links/metadata if license unclear. |
| B | Edge Impulse Embedded ML Courseware | https://github.com/edgeimpulse/courseware-embedded-machine-learning | Slides, readings, sample questions, videos | Useful applied ML/TinyML examples for extension modules. | Videos use standard YouTube license; avoid mirroring videos. |
| B | rasbt Machine Learning with PyTorch and Scikit-Learn code | https://github.com/rasbt/machine-learning-book | Notebooks/code | High-quality scikit-learn/PyTorch code examples. | Code repository for a commercial book; ingest code with attribution, not book text. |
| B | Ruban Iris Classification | https://github.com/Ruban2205/Iris_Classification | Notebook, PDF notebook export, dataset, Streamlit app | Simple project-format Iris classification with notebook PDF and app assets. | MIT license; useful as "end-to-end student project" example. |
| B | Machine-Learning-Class/Machine-learning | https://github.com/Machine-Learning-Class/Machine-learning | Chinese syllabus, course links, PPT/readings references | Chinese ML theory/method course referencing 西瓜书, 统计学习方法, CS229. | README warns PPT content must not be used commercially; treat as metadata/reference unless terms are clear. |
| B | Vay-keen 西瓜书学习笔记 | https://github.com/Vay-keen/Machine-learning-learning-notes | Markdown notes | Chapter-by-chapter Chinese notes around 周志华《机器学习》. | Good for concept-aligned Chinese text; check license before bulk ingestion. |
| B | relph1119 WatermelonBook training repo | https://github.com/relph1119/machinelearning-watermelonbook | Jupyter notebooks, course materials | 西瓜书 training camp materials, likely includes notebooks and references. | Large repo; check license and avoid copyrighted textbook scans. |
| A/B | Datawhale 南瓜书 | https://github.com/datawhalechina/pumpkin-book | PDF releases, docs, formula derivations, images | Best open companion for 西瓜书 formulas; ideal for formula RAG and derivation chunks. | Use 南瓜书, not pirated 西瓜书 PDFs. Check repo license before redistribution. |
| C | 周志华《机器学习》（西瓜书）official/commercial book | Publisher/bookstores | Book text/PDF if purchased | Core textbook reference for syllabus alignment. | Do not ingest pirated PDF mirrors into repo. Store only citation metadata unless we have licensed copy and permission. |
| C | Bilibili 西瓜书 lecture playlists | Example: https://www.bilibili.com/video/BV1ks2bYGETs/ | Videos, sometimes PPT links in comments | Useful for human review and timestamp metadata. | Do not mirror videos/PPT unless uploader license explicitly allows it. Store URLs and metadata only. |
| C | Coursera/Andrew Ng assignment mirrors | Many GitHub mirrors | Notes, labs, assignment solutions | Useful for inspiration. | Avoid ingesting copyrighted Coursera assignments/solutions into public data. Prefer CS229 official handouts. |

## Direct Crawl Plan

1. Create local folders:
   - `data/raw/github_repos/`
   - `data/raw/course_pages/`
   - `data/raw/pdfs/`
   - `data/raw/slides/`
   - `data/raw/notebooks/`
   - `data/raw/videos_metadata/`
   - `data/manifest/`
2. First batch:
   - `neonwatty/machine-learning-refined`
   - `mlds-lab/COMPSCI-589`
   - `Yorko/mlcourse.ai`
   - `dafriedman97/mlbook`
   - `Nyandwi/machine_learning_complete`
   - `datawhalechina/pumpkin-book`
3. Second batch:
   - scikit-learn examples and generated notebooks
   - Iris-specific projects/notebooks
   - VU/UvA public lecture pages
   - LMU IML course
4. Generate a manifest JSONL per asset:
   - `source_url`
   - `repo`
   - `license`
   - `asset_type` (`pdf`, `pptx`, `ipynb`, `py`, `image`, `video_url`, `dataset`)
   - `topic_tags`
   - `language`
   - `local_path`
   - `redistribution_policy`
   - `ingestion_status`

## Topics To Cover First

| Topic | Recommended sources |
|---|---|
| 鸢尾花 / classification hello world | UCI Iris, scikit-learn Iris examples, Ruban Iris Classification, SHAP Iris |
| Linear regression | ML Engineering, Machine Learning Refined, Machine Learning from Scratch, CS229 notes |
| Logistic regression | mlcourse.ai, CS229 notes, Machine Learning from Scratch, Machine Learning Refined |
| Decision trees | scikit-learn examples, dtreeviz, mlcourse.ai, COMPSCI-589 |
| Evaluation / confusion matrix | mlcourse.ai, ML Engineering, VU ML, scikit-learn examples |
| Overfitting / regularization | Machine Learning Refined, CS229 notes, COMPSCI-589 |
| PCA / clustering | mlcourse.ai, CS229 notes, COMPSCI-589 |
| 西瓜书公式推导 | Datawhale 南瓜书, Vay-keen notes |
| Visualization code | scikit-learn examples, ML Visualized, dtreeviz, Nyandwi notebooks |
| Videos metadata | ML Engineering, mlcourse.ai, VU ML, UvA ML1, LMU IML |

## Legal / Safety Notes

- Keep raw downloaded files under `data/`; never commit them.
- Prefer open repositories with explicit licenses.
- For copyrighted books such as 西瓜书 or commercial textbook PDFs, store bibliographic metadata and purchase/reference links, not the PDF.
- For YouTube/Bilibili, store only video URL, title, timestamps, and transcript if license/terms allow; do not mirror raw video by default.
- For GitHub repos with unclear license, keep only URL metadata until license is verified.

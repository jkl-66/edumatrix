# Implementation Plan - 5-Dimensional Adaptive Resource Hub (5维自适应资源中心)

This plan outlines the design and implementation of an **Adaptive Resource Hub (自适应资源学习中心)** on the student Dashboard. Instead of displaying static cards that jump blindly to the Notes tab, the dashboard will now render a **5-Dimensional Resource Matrix** for the student's weakest or next-up learning concepts. Each resource can be **individually generated asynchronously** and **rendered/played in-place**, with full database persistence linking directly into the student's study notebook.

---

## User Review Required

Key architectural decisions requiring confirmation.

> [!IMPORTANT]
> **1. Unified Persistence using `DBNote`**:
> To ensure that individually generated resources (Lecture Notes, Mindmaps, Coding Sandbox cases, and Video Scripts) are permanently saved and searchable, we will automatically save them to the `notes` SQLite table using specific tags:
> - `tag = ["专业讲义"]` for Lecture Notes.
> - `tag = ["思维导图"]` for Mindmaps.
> - `tag = ["代码案例"]` for Coding Sandbox Cases.
> - `tag = ["视频脚本"]` for Video Scripts.
> When the dashboard loads, it will query the database to determine which resources have already been generated, displaying a green `已生成` (View/Open) badge or a gray `未生成` (Generate) button.
>
> **2. Interactive Inline Resource Drawer/Viewer**:
> Clicking on a resource sub-card will expand an inline viewer or modal:
> - If **Not Generated**: Shows the resource's structural overview/outline and a "一键单独生成" (Generate Separately) button.
> - If **Generating**: Shows an inline loading spinner and progress status.
> - If **Generated**: Renders the Markdown (with KaTeX) / Mermaid diagrams / code snippets / videos directly in-place, and provides an "在独立工作空间打开" (Open in Workspace) shortcut.

---

## Proposed Changes

### Backend Components

#### [MODIFY] [app/utils/recommendation_engine.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/recommendation_engine.py)
* Refactor `get_smart_recommendations` to return **Concept-centric** recommendations instead of flat Resource-centric items.
* For the top 3 weak or target concepts identified from the student profile (e.g. "池化层", "梯度下降"):
  * Query the `notes` table in the database to check if notes for `concept` with tags `"专业讲义"`, `"思维导图"`, `"代码案例"`, or `"视频脚本"` already exist.
  * For each concept, return a structural metadata object containing:
    - `concept`: e.g. "池化层"
    - `mastery`: Current mastery score (e.g. 0.79)
    - `badge`: e.g. "🔥 薄弱强化"
    - `reason`: Pedagogical diagnostic reasoning.
    - `resources`: A dictionary mapping the 5 dimensions, each containing:
      - `role`: e.g., "理论教授", "逻辑画师", "极客助教", "考官智能体", "虚拟导演"
      - `resource_type`: e.g., "专业讲义", "思维导图", "代码实操案例", "练习题", "虚拟人视频脚本"
      - `overview`: A static or dynamic structural overview/outline of what this resource covers.
      - `status`: `"generated"` (if existing notes are found in DB) or `"not_generated"`.
      - `note_id`: Note ID of the generated resource (if status is `"generated"`).

#### [MODIFY] [stream_api.py](file:///d:/project-edumatrix/edumatrix-main/stream_api.py)
* Refactor `regenerate_component` (`POST /api/stream/regenerate` endpoint):
  * When a single component is successfully generated (using `swarm.async_generator.generate`), **automatically insert it into the `notes` table** in the SQLite database:
    - Generate a unique ID (UUID).
    - Insert a `DBNote` row:
      - `id`: UUID string.
      - `student_id`: current student ID.
      - `source`: `"adaptive_hub"`.
      - `content`: generated Markdown/Mermaid content.
      - `tags`: `[resource_type]`.
      - `concepts`: `[query]`.
  * Return the generated `content` and the newly created `note_id` so the frontend can store it:
    ```json
    {
      "status": "success",
      "content": "...",
      "note_id": "note-uuid-string"
    }
    ```

---

### Frontend Components

#### [MODIFY] [Dashboard.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Dashboard.vue)
* **Reconstruct UI Layout**:
  * Render recommended concepts as structured **expansion panels** or grid cards.
  * Within each concept card, render the **5-Dimensional Resource Matrix** as a grid of 5 sub-cards:
    1. 📝 **专业讲义 (Lecture Notes)**
    2. 🗺️ **思维导图 (Mindmap)**
    3. 💻 **代码沙箱 (Code Sandbox)**
    4. ✍️ **随堂小测 (Quiz)**
    5. 🎬 **微课视频 (Video Script)**
  * Each sub-card displays:
    - Title & Modality Icon.
    - AI Overview/Outline.
    - Generation Status Badge: `已就绪 (绿色)` or `待生成 (灰色)`.
* **Implement Inline Generation & Viewer (单独异步生成与展示)**:
  * Add a drawer/modal `activeResourceViewer` when a sub-card is clicked.
  * If **not generated**, clicking `"开始单独生成"` triggers:
    - An async call to `regenerateComponent(studentId, role, resourceType, concept)`.
    - Shows an inline loader with real-time status.
    - Saves the returned content in local memory and displays it using standard markdown/mermaid/code renderers.
  * If **already generated**, load the note content (via an API call or returned note ID) and show it immediately.
* **Implement "Open in Workspace" shortcuts**:
  - Lecture Notes / Mindmap -> Redirect to `/learn` or `/notes?search=concept`.
  - Code Sandbox -> Redirect to `/learn` and switch to Code tab with the code preloaded.
  - Video script -> Open the `VideoRenderPanel` directly.

---

## Verification Plan

### Automated Tests
* Update `tests/test_recommendation_engine.py` to verify that `get_smart_recommendations` correctly yields the expanded 5-dimensional resource matrix structures with generation statuses.
* Run backend tests:
  ```powershell
  python -m unittest tests/test_recommendation_engine.py
  ```

### Manual Verification
1. Open the Dashboard.
2. Select the `"池化层"` concept card.
3. Observe the 5 resource sub-cards and their respective AI overviews.
4. Click `"代码沙箱案例"`. Assert that it is in the `未生成` state.
5. Click `"一键单独生成"`. Verify that the loading spinner appears, and after 5-10 seconds, the Python code is generated and displayed inline.
6. Refresh the Dashboard. Verify that `"代码沙箱案例"` now displays a green `已就绪` badge.
7. Click the code card and click `"进入沙箱运行"`. Verify it redirects to the Code sandbox and preloads the generated Python code.

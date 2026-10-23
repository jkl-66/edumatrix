from __future__ import annotations

"""Build the deterministic Chinese data-structures and algorithms course bundle.

The repository is already vendored under ``data/raw`` at a frozen commit.  The
builder reads the upstream Markdown with ``git show`` so normal application
startup never needs a network connection.  Each output chapter keeps the
upstream file list, blob hash, revision and license notice in the manifest.
"""

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT / "data" / "raw" / "github_repos" / "hello-algo"
OUTPUT_DIR = ROOT / "data" / "curated" / "data_structures_algorithms_v1"
MANIFEST_PATH = OUTPUT_DIR / "course_manifest.json"
PROCESSING_REPORT_PATH = OUTPUT_DIR / "processing_report.json"
LICENSE_PATH = OUTPUT_DIR / "LICENSE-AND-ATTRIBUTION.upstream.md"
REPOSITORY_KEY = "hello-algo"
REPOSITORY_URL = "https://github.com/krahets/hello-algo"
REVISION = "28c1e74c1d3594fca7cc41b78a6bd18b700c5ce9"
PARSER_VERSION = "edumatrix-hello-algo-zh-hans-v1"
LICENSE_SPDX = "CC-BY-NC-SA-4.0"


# Stable chapter order mirrors the upstream learning progression.  Knowledge
# points are intentionally finer than chapters so diagnostics and path plans
# can target a concrete algorithm rather than a whole book section.
CHAPTERS = [
    ("chapter_introduction", "编程与算法导论", [("DSA-KP-01", "算法问题建模", "foundation", [])]),
    ("chapter_computational_complexity", "复杂度分析与性能边界", [("DSA-KP-02", "时间与空间复杂度", "foundation", ["DSA-KP-01"])]),
    ("chapter_array_and_linkedlist", "数组、字符串与链表", [("DSA-KP-03", "数组与字符串", "foundation", ["DSA-KP-02"]), ("DSA-KP-04", "链表与指针操作", "foundation", ["DSA-KP-03"])]),
    ("chapter_stack_and_queue", "栈、队列与双端队列", [("DSA-KP-05", "栈与队列", "foundation", ["DSA-KP-04"])]),
    ("chapter_hashing", "哈希表与缓存结构", [("DSA-KP-06", "哈希表与冲突处理", "core", ["DSA-KP-03"]), ("DSA-KP-07", "LRU 缓存设计", "core", ["DSA-KP-05", "DSA-KP-06"])]),
    ("chapter_tree", "树、二叉搜索树与遍历", [("DSA-KP-08", "树与二叉树遍历", "core", ["DSA-KP-05"]), ("DSA-KP-09", "二叉搜索树与平衡", "core", ["DSA-KP-08"]), ("DSA-KP-10", "Trie 前缀树", "advanced", ["DSA-KP-06", "DSA-KP-08"])]),
    ("chapter_heap", "堆、优先队列与 Top-K", [("DSA-KP-11", "堆与优先队列", "core", ["DSA-KP-08"]), ("DSA-KP-12", "Top-K 与任务调度", "advanced", ["DSA-KP-11"])]),
    ("chapter_graph", "图表示、搜索与最短路", [("DSA-KP-13", "图表示与遍历", "core", ["DSA-KP-08"]), ("DSA-KP-14", "BFS、DFS 与拓扑排序", "core", ["DSA-KP-13"]), ("DSA-KP-15", "最短路与连通性", "advanced", ["DSA-KP-14"])]),
    ("chapter_sorting", "排序算法与稳定性", [("DSA-KP-16", "比较排序", "core", ["DSA-KP-02", "DSA-KP-03"]), ("DSA-KP-17", "归并、快速与堆排序", "core", ["DSA-KP-16"]), ("DSA-KP-18", "线性排序与稳定性", "advanced", ["DSA-KP-16"])]),
    ("chapter_searching", "查找、二分与边界", [("DSA-KP-19", "二分查找与边界", "core", ["DSA-KP-16"]), ("DSA-KP-20", "哈希查找与双指针", "advanced", ["DSA-KP-06", "DSA-KP-19"])]),
    ("chapter_divide_and_conquer", "递归、分治与组合构造", [("DSA-KP-21", "递归与分治", "core", ["DSA-KP-02", "DSA-KP-03"])]),
    ("chapter_backtracking", "回溯、剪枝与搜索", [("DSA-KP-22", "回溯与剪枝", "advanced", ["DSA-KP-05", "DSA-KP-21"])]),
    ("chapter_greedy", "贪心算法与可证明选择", [("DSA-KP-23", "贪心策略", "advanced", ["DSA-KP-16", "DSA-KP-21"])]),
    ("chapter_dynamic_programming", "动态规划与状态设计", [("DSA-KP-24", "动态规划建模", "advanced", ["DSA-KP-21"]), ("DSA-KP-25", "背包、区间与路径 DP", "advanced", ["DSA-KP-24"])]),
]


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


_SOURCE_CACHE: dict[str, bytes] = {}
_CHAPTER_FILES: dict[str, list[str]] = {}


def _load_chapter(directory: str) -> None:
    if directory in _CHAPTER_FILES:
        return
    result = subprocess.run(
        ["git", "-C", str(REPOSITORY), "ls-tree", "-r", "--format=%(objectname) %(path)", REVISION, "--", f"docs/{directory}"],
        check=True,
        capture_output=True,
    )
    entries = [line.split(" ", 1) for line in result.stdout.decode("utf-8").splitlines() if " " in line and line.endswith(".md")]
    files = [path for _oid, path in entries]
    if entries:
        batch = subprocess.Popen(
            ["git", "-C", str(REPOSITORY), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        payload = ("".join(f"{oid}\n" for oid, _path in entries)).encode("ascii")
        stdout, stderr = batch.communicate(payload)
        if batch.returncode != 0:
            raise ValueError(f"unable to read frozen source blobs: {stderr.decode('utf-8', errors='replace')}")
        position = 0
        for oid, path in entries:
            header_end = stdout.find(b"\n", position)
            if header_end < 0:
                raise ValueError(f"invalid git batch response: {path}")
            header = stdout[position:header_end].decode("ascii", errors="replace").split()
            if len(header) < 3 or header[0] != oid or header[1] != "blob":
                raise ValueError(f"frozen source is not a blob: {path}")
            size = int(header[2])
            start = header_end + 1
            end = start + size
            _SOURCE_CACHE[path] = stdout[start:end].replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            position = end + 1
    _CHAPTER_FILES[directory] = sorted(files)


def git_files(directory: str) -> list[str]:
    _load_chapter(directory)
    return list(_CHAPTER_FILES[directory])


def git_blob(path: str) -> bytes:
    if path in _SOURCE_CACHE:
        return _SOURCE_CACHE[path]
    command = ["git", "-C", str(REPOSITORY), "show", f"{REVISION}:{path}"]
    result = None
    for _attempt in range(3):
        result = subprocess.run(command, check=False, capture_output=True)
        if result.returncode == 0:
            break
    if result is None or result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", errors="replace") if result else ""
        raise ValueError(f"frozen_source_missing:{path}:{detail.strip()}")
    return result.stdout.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def build_course() -> dict:
    if not REPOSITORY.is_dir():
        raise ValueError(f"vendored repository missing: {REPOSITORY}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    license_raw = (
        "# 上游资料许可与署名\n\n"
        f"固定仓库：{REPOSITORY_URL}\n\n"
        f"固定 commit：`{REVISION}`\n\n"
        "本课程以 hello-algo 仓库 zh-hans/docs 下的中文 Markdown 为主教材，"
        "保留章节文件的来源路径与内容哈希。上游许可为 CC BY-NC-SA 4.0："
        "使用时保留署名、非商业使用、相同方式共享并标注改编。"
        "本包由 EduMatrix 将同一章节的中文页面按章节串联，新增教学标题和知识点映射；"
        "不把外部链接、图片二进制或代码运行环境作为启动时依赖。\n"
    ).encode("utf-8")
    LICENSE_PATH.write_bytes(license_raw)

    all_points = []
    files = []
    for order, (directory, title, points) in enumerate(CHAPTERS):
        source_paths = git_files(directory)
        if not source_paths:
            raise ValueError(f"no Chinese Markdown found for {directory}")
        source_blobs = [git_blob(path) for path in source_paths]
        source_raw = b"\n\n".join(source_blobs)
        source_relative = list(source_paths)
        body = (
            f"# {title}\n\n"
            f"> 来源：[{REPOSITORY_KEY}]({REPOSITORY_URL}/tree/{REVISION}/docs/{directory})  \n"
            f"> 固定版本：`{REVISION}`  \n"
            "> 课程角色：主教材（中文章节）；本页为按主题串联的教学阅读入口。  \n"
            "> 改编说明：保留上游章节正文与代码示例，补充 EduMatrix 的知识点和先修映射；不宣称行业认证。\n\n"
            + source_raw.decode("utf-8", errors="replace")
            + "\n"
        ).encode("utf-8")
        output_path = f"chapters/{order:02d}_{title}.md"
        destination = OUTPUT_DIR / output_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        point_codes = [item[0] for item in points]
        all_points.extend(
            {"code": code, "title": point_title, "level": level, "prerequisites": prerequisites}
            for code, point_title, level, prerequisites in points
        )
        files.append(
            {
                "chapter_order": order,
                "title": title,
                "repository_key": REPOSITORY_KEY,
                "repository_url": REPOSITORY_URL,
                "git_revision": REVISION,
                "source_path": ";".join(source_relative),
                "source_type": "md",
                "source_bytes": len(source_raw),
                "source_sha256": sha256(source_raw),
                "path": output_path,
                "bytes": len(body),
                "sha256": sha256(body),
                "parser_version": PARSER_VERSION,
                "license_spdx": LICENSE_SPDX,
                "license_file": LICENSE_PATH.name,
                "license_sha256": sha256(license_raw),
                "obligations": ["attribution", "noncommercial", "share_alike", "indicate_changes"],
                "attribution": ["Krahets / Hello 算法贡献者"],
                "knowledge_point_codes": point_codes,
                "source_role": "中文主教材",
                "chapter_key": f"hello-algo:{directory}",
                "chapter_position": order,
                "conversion": {
                    "strategy": "frozen_git_markdown_concatenation",
                    "source_file_count": len(source_paths),
                    "external_links_imported": 0,
                    "binary_assets_imported": 0,
                },
            }
        )

    manifest = {
        "schema_version": "edumatrix.course-version-manifest.v1",
        "manifest_version": "course-data-structures-algorithms-engineering-1.0.0",
        "generated_at": "2026-08-31T00:00:00+08:00",
        "course_id": "course-data-structures-algorithms-engineering-v1",
        "title": "数据结构与算法工程实践：从基础结构到算法设计与岗位刷题",
        "subject": "计算机科学 / 数据结构与算法",
        "description": "以中文《Hello 算法》为主教材，覆盖复杂度、线性结构、树、堆、图、排序查找、回溯、贪心、动态规划和工程题型。",
        "domain_pack": "domain-data-structures-algorithms-engineering-v1",
        "knowledge_point_version": "data-structures-algorithms-kp-1.0.0",
        "language": "zh-CN",
        "content_origin": "Hello 算法中文文档固定 commit；章节正文、来源角色和知识点映射均保留可追溯元数据。",
        "license": "CC BY-NC-SA 4.0；署名、非商业、相同方式共享并标注改编。详见 LICENSE-AND-ATTRIBUTION.upstream.md。",
        "visibility": "public",
        "status": "published",
        "tags": ["副课程", "数据结构", "算法", "中文教材", "岗位实践"],
        "source_roles": {
            "primary": "Hello 算法中文章节",
            "theory": "OI Wiki（待补充的理论扩展位）",
            "practice": "labuladong（待补充的题型扩展位）",
            "career": "CS-Notes（待补充的岗位扩展位）",
        },
        "claim_boundary": "基于固定公开中文教材的课程工程演示；不宣称行业认证。",
        "external_material_policy": "启动和运行不联网；OI Wiki、labuladong、CS-Notes 作为后续可审核扩展来源，不混入本版主答案。",
        "source_audit": {
            "approved_repository_count": 1,
            "repositories": [{"key": REPOSITORY_KEY, "url": REPOSITORY_URL, "git_revision": REVISION}],
        },
        "processing": {
            "parser_version": PARSER_VERSION,
            "deterministic": True,
            "network_required": False,
            "external_model_used": False,
            "source_language": "zh-CN",
        },
        "knowledge_points": all_points,
        "files": files,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    report = {
        "schema_version": "edumatrix.course-processing-report.v1",
        "course_id": manifest["course_id"],
        "source_revision": REVISION,
        "parser_version": PARSER_VERSION,
        "output_manifest_sha256": sha256(MANIFEST_PATH.read_bytes()),
        "chapter_count": len(files),
        "knowledge_point_count": len(all_points),
        "license_sha256": sha256(license_raw),
        "network_calls": 0,
        "external_model_calls": 0,
        "source_file_count": sum(int(item["conversion"]["source_file_count"]) for item in files),
    }
    PROCESSING_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


if __name__ == "__main__":
    result = build_course()
    print(json.dumps({"manifest": str(MANIFEST_PATH), "chapters": len(result["files"]), "knowledge_points": len(result["knowledge_points"])}, ensure_ascii=False))

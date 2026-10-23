#!/usr/bin/env python3
"""Build a reproducible product/code map for the 7.20 and current versions."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont, ImageOps


SOURCE_SUFFIXES = {".py", ".js", ".vue", ".json", ".md", ".bat", ".ps1"}
SKIP_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    "outputs",
    "data",
    "vendor",
    "reports",
    ".agents",
    ".codex",
}


def text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="gb18030", errors="replace")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for path in root.iterdir():
        if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
            result.append(path)
    for product_dir in (root / "app", root / "frontend", root / "scripts"):
        if not product_dir.exists():
            continue
        for current_dir, dirnames, filenames in os.walk(product_dir):
            dirnames[:] = sorted(
                name for name in dirnames if name not in SKIP_PARTS and not name.startswith(".")
            )
            current_path = Path(current_dir)
            for filename in sorted(filenames):
                path = current_path / filename
                if path.suffix.lower() in SOURCE_SUFFIXES:
                    result.append(path)
    # Keep test modules at the tests root. Runtime fixtures and copied sample
    # projects under tests/ are evidence inputs, not application source.
    test_root = root / "tests"
    if test_root.exists():
        for path in sorted(test_root.glob("*.py")):
            result.append(path)
    return sorted(result)


def line_count(content: str) -> int:
    return len(content.splitlines())


def file_inventory(root: Path) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for path in source_files(root):
        relative = path.relative_to(root).as_posix()
        content = text(path)
        inventory[relative] = {
            "suffix": path.suffix.lower(),
            "bytes": path.stat().st_size,
            "lines": line_count(content),
            "sha256": sha256(path),
        }
    return inventory


def parse_imported_views(router_source: str) -> dict[str, str]:
    imports: dict[str, str] = {}
    pattern = re.compile(
        r"const\s+(?P<symbol>[A-Za-z0-9_]+)\s*=\s*\(\)\s*=>\s*import\(['\"](?P<path>[^'\"]+)['\"]\)"
    )
    for match in pattern.finditer(router_source):
        imports[match.group("symbol")] = match.group("path")
    return imports


def balanced_objects(source: str, marker: str = "const routes") -> list[str]:
    start = source.find(marker)
    if start < 0:
        return []
    array_start = source.find("[", start)
    if array_start < 0:
        return []
    objects: list[str] = []
    depth = 0
    object_start: int | None = None
    quote: str | None = None
    escaped = False
    for index in range(array_start + 1, len(source)):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == "{":
            if depth == 0:
                object_start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and object_start is not None:
                objects.append(source[object_start : index + 1])
                object_start = None
        elif char == "]" and depth == 0:
            break
    return objects


def first_match(pattern: str, source: str) -> str | None:
    match = re.search(pattern, source, flags=re.S)
    return match.group(1).strip() if match else None


def parse_vue_routes(root: Path) -> list[dict[str, Any]]:
    router = root / "frontend" / "src" / "router" / "index.js"
    if not router.exists():
        return []
    source = text(router)
    imports = parse_imported_views(source)
    routes: list[dict[str, Any]] = []
    for order, block in enumerate(balanced_objects(source), 1):
        path_value = first_match(r"\bpath\s*:\s*['\"]([^'\"]+)['\"]", block)
        if not path_value:
            continue
        name = first_match(r"\bname\s*:\s*['\"]([^'\"]+)['\"]", block)
        component = first_match(r"\bcomponent\s*:\s*([A-Za-z0-9_]+)", block)
        guard = first_match(r"\bbeforeEnter\s*:\s*([^,}\n]+)", block)
        alias_raw = first_match(r"\balias\s*:\s*(\[[^\]]+\]|['\"][^'\"]+['\"])", block)
        roles_raw = first_match(r"\broles\s*:\s*\[([^\]]*)\]", block)
        roles = re.findall(r"['\"]([^'\"]+)['\"]", roles_raw or "")
        routes.append(
            {
                "order": order,
                "path": path_value,
                "name": name,
                "component": component,
                "view": imports.get(component or ""),
                "guard": guard,
                "aliases": re.findall(r"['\"]([^'\"]+)['\"]", alias_raw or ""),
                "roles": roles,
                "course_scoped": bool(re.search(r"courseScoped\s*:\s*true", block)),
                "redirect": "compatibilityRedirect" in block or "redirect" in block,
                "raw": re.sub(r"\s+", " ", block)[:1000],
            }
        )
    return routes


def strip_vue_expressions(value: str) -> str:
    value = re.sub(r"\{\{.*?\}\}", "", value, flags=re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_js_imports(source: str) -> list[dict[str, Any]]:
    imports: list[dict[str, Any]] = []
    pattern = re.compile(
        r"import\s+(?P<symbols>\{.*?\}|[A-Za-z0-9_$]+)\s+from\s+['\"](?P<module>[^'\"]+)['\"]",
        re.S,
    )
    for match in pattern.finditer(source):
        raw_symbols = match.group("symbols").strip("{} \n\r\t")
        symbols = []
        for symbol in raw_symbols.split(","):
            symbol = symbol.strip()
            if symbol:
                symbols.append(symbol.split(" as ")[-1].strip())
        imports.append({"module": match.group("module"), "symbols": symbols})
    return imports


def parse_vue_view(path: Path, root: Path) -> dict[str, Any]:
    source = text(path)
    imports = parse_js_imports(source)
    api_imports = [item for item in imports if "/api/" in item["module"] or item["module"].startswith("../api")]
    components = [
        item
        for item in imports
        if "/components/" in item["module"] or item["module"].startswith("../components")
    ]
    tags = re.findall(r"<([A-Z][A-Za-z0-9]+)\b", source)
    buttons = [strip_vue_expressions(item) for item in re.findall(r"<button\b[^>]*>(.*?)</button>", source, re.S | re.I)]
    buttons += [strip_vue_expressions(item) for item in re.findall(r"<UiButton\b[^>]*>(.*?)</UiButton>", source, re.S)]
    headings = [
        strip_vue_expressions(item)
        for item in re.findall(r"<(?:h1|h2|h3|h4)\b[^>]*>(.*?)</(?:h1|h2|h3|h4)>", source, re.S | re.I)
    ]
    labels = re.findall(r"\blabel\s*:\s*['\"]([^'\"]+)['\"]", source)
    titles = re.findall(r"\btitle\s*:\s*['\"]([^'\"]+)['\"]", source)
    literals = re.findall(r"['\"](/api/[^'\"?# ]+)", source)
    route_targets = re.findall(r"(?:router\.push|to=)\s*\(?\s*['\"]([^'\"]+)['\"]", source)
    function_names = re.findall(r"\b(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", source)
    function_names += re.findall(r"\bconst\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(", source)
    return {
        "file": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "lines": line_count(source),
        "api_imports": api_imports,
        "component_imports": components,
        "component_tags": sorted(set(tags)),
        "buttons": sorted(set(filter(None, buttons))),
        "headings": sorted(set(filter(None, headings))),
        "labels": sorted(set(filter(None, labels))),
        "titles": sorted(set(filter(None, titles))),
        "endpoint_literals": sorted(set(literals)),
        "route_targets": sorted(set(route_targets)),
        "function_names": sorted(set(function_names)),
        "template_elements": len(re.findall(r"<[A-Za-z][^>]*>", source)),
        "v_if_count": len(re.findall(r"\bv-if=", source)),
        "v_for_count": len(re.findall(r"\bv-for=", source)),
    }


def parse_frontend_api(path: Path, root: Path) -> dict[str, Any]:
    source = text(path)
    exports = re.findall(
        r"export\s+(?:async\s+)?(?:function|const)\s+([A-Za-z_$][A-Za-z0-9_$]*)", source
    )
    calls: list[dict[str, str | None]] = []
    for match in re.finditer(
        r"\b(?:api|axios|client)\.(get|post|put|patch|delete)\s*\(\s*([`'\"])(.*?)\2",
        source,
        re.S | re.I,
    ):
        calls.append({"method": match.group(1).upper(), "path": match.group(3), "function": None})
    return {
        "file": path.relative_to(root).as_posix(),
        "lines": line_count(source),
        "exports": sorted(set(exports)),
        "calls": calls,
    }


def decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = decorator_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "<dynamic>"
    return None


def assigned_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets: list[ast.expr]
    if isinstance(node, ast.AnnAssign):
        targets = [node.target]
    else:
        targets = list(node.targets)
    return [target.id for target in targets if isinstance(target, ast.Name)]


def model_field_names(node: ast.ClassDef) -> list[str]:
    fields: list[str] = []
    for item in node.body:
        if not isinstance(item, (ast.Assign, ast.AnnAssign)):
            continue
        fields.extend(name for name in assigned_names(item) if not name.startswith("_"))
    return sorted(set(fields))


def parse_python(path: Path, root: Path) -> dict[str, Any]:
    source = text(path)
    result: dict[str, Any] = {
        "file": path.relative_to(root).as_posix(),
        "lines": line_count(source),
        "routes": [],
        "router_definitions": [],
        "classes": [],
        "orm_models": [],
        "functions": [],
        "imports": [],
        "import_bindings": [],
        "router_registrations": [],
        "parse_error": None,
    }
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        result["parse_error"] = f"{error.msg} at {error.lineno}:{error.offset}"
        return result
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name) or target.id != "router":
                    continue
                if not isinstance(node.value, ast.Call):
                    continue
                owner = decorator_name(node.value.func)
                if owner.rsplit(".", 1)[-1] != "APIRouter":
                    continue
                keywords = {kw.arg: literal_string(kw.value) for kw in node.value.keywords if kw.arg}
                result["router_definitions"].append(
                    {
                        "line": node.lineno,
                        "prefix": keywords.get("prefix") or "",
                        "tags": keywords.get("tags"),
                        "owner": owner,
                    }
                )
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [alias.asname or alias.name for alias in node.names]
                for alias in node.names:
                    result["import_bindings"].append(
                        {"module": module, "name": alias.name, "local_name": alias.asname or alias.name}
                    )
            else:
                module = ""
                names = [alias.asname or alias.name for alias in node.names]
                for alias in node.names:
                    result["import_bindings"].append(
                        {"module": alias.name, "name": None, "local_name": alias.asname or alias.name}
                    )
            result["imports"].append({"module": module, "names": names})
        if isinstance(node, ast.ClassDef):
            bases = [decorator_name(base) for base in node.bases]
            result["classes"].append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "bases": bases,
                    "methods": [item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))],
                }
            )
            if any(base.rsplit(".", 1)[-1] in {"Base", "SQLModel", "DeclarativeBase"} for base in bases):
                table_name = None
                for item in node.body:
                    if not isinstance(item, (ast.Assign, ast.AnnAssign)):
                        continue
                    if "__tablename__" in assigned_names(item):
                        table_name = literal_string(item.value)
                        break
                result["orm_models"].append(
                    {
                        "name": node.name,
                        "line": node.lineno,
                        "table": table_name,
                        "bases": bases,
                        "fields": model_field_names(node),
                    }
                )
        if isinstance(node, ast.Call) and decorator_name(node.func).rsplit(".", 1)[-1] == "include_router":
            result["router_registrations"].append(
                {
                    "line": node.lineno,
                    "application": decorator_name(node.func).rsplit(".", 1)[0],
                    "router_symbol": decorator_name(node.args[0]) if node.args else "",
                    "prefix": next(
                        (literal_string(keyword.value) or "" for keyword in node.keywords if keyword.arg == "prefix"),
                        "",
                    ),
                }
            )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result["functions"].append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                    "args": [arg.arg for arg in node.args.args],
                }
            )
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                name = decorator_name(decorator.func)
                method = name.rsplit(".", 1)[-1].upper()
                if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "WEBSOCKET"}:
                    continue
                route_path = literal_string(decorator.args[0]) if decorator.args else None
                keywords = {kw.arg: literal_string(kw.value) for kw in decorator.keywords if kw.arg}
                result["routes"].append(
                    {
                        "method": method,
                        "path": route_path,
                        "function": node.name,
                        "line": node.lineno,
                        "decorator_owner": name.rsplit(".", 1)[0] if "." in name else name,
                        "summary": keywords.get("summary"),
                    }
                )
    result["classes"] = sorted(result["classes"], key=lambda item: item["line"])
    result["orm_models"] = sorted(result["orm_models"], key=lambda item: item["line"])
    result["functions"] = sorted(result["functions"], key=lambda item: item["line"])
    result["routes"] = sorted(result["routes"], key=lambda item: item["line"])
    result["router_registrations"] = sorted(result["router_registrations"], key=lambda item: item["line"])
    return result


def module_file(module: str) -> str:
    return f"{module.replace('.', '/')}.py" if module else ""


def join_api_path(*parts: str | None) -> str:
    value = "/".join(str(part or "").strip("/") for part in parts if part)
    return f"/{value}" if value else "/"


def resolve_router_registration_map(python_modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    module_by_file = {module["file"]: module for module in python_modules}
    registrations: list[dict[str, Any]] = []
    for registrar in python_modules:
        bindings = {binding["local_name"]: binding for binding in registrar["import_bindings"]}
        for registration in registrar["router_registrations"]:
            binding = bindings.get(registration["router_symbol"])
            imported_file = module_file(binding["module"]) if binding else ""
            imported_module = module_by_file.get(imported_file)
            definitions = imported_module["router_definitions"] if imported_module else []
            router_prefix = definitions[0]["prefix"] if len(definitions) == 1 else ""
            registrations.append(
                {
                    **registration,
                    "registered_in": registrar["file"],
                    "imported_module": binding["module"] if binding else None,
                    "imported_name": binding["name"] if binding else None,
                    "imported_file": imported_file or None,
                    "router_prefix": router_prefix,
                    "final_prefix": join_api_path(registration["prefix"], router_prefix),
                    "definition_count": len(definitions),
                    "resolved": bool(imported_module and len(definitions) == 1),
                }
            )
    return registrations


def resolve_backend_routes(
    python_modules: list[dict[str, Any]], registrations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    registration_by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for registration in registrations:
        if registration["imported_file"]:
            registration_by_file[registration["imported_file"]].append(registration)

    resolved_routes: list[dict[str, Any]] = []
    for module in python_modules:
        router_prefix = module["router_definitions"][0]["prefix"] if len(module["router_definitions"]) == 1 else ""
        module_registrations = registration_by_file.get(module["file"], [])
        for route in module["routes"]:
            owner = route["decorator_owner"].rsplit(".", 1)[-1]
            if owner == "app":
                resolved_routes.append(
                    {
                        **route,
                        "file": module["file"],
                        "router_prefix": "",
                        "registration_prefix": "",
                        "final_path": join_api_path(route["path"]),
                        "registered": True,
                        "registered_in": module["file"],
                    }
                )
            elif owner == "router" and module_registrations:
                for registration in module_registrations:
                    resolved_routes.append(
                        {
                            **route,
                            "file": module["file"],
                            "router_prefix": router_prefix,
                            "registration_prefix": registration["prefix"],
                            "final_path": join_api_path(
                                registration["prefix"], router_prefix, route["path"]
                            ),
                            "registered": registration["resolved"],
                            "registered_in": registration["registered_in"],
                        }
                    )
            else:
                resolved_routes.append(
                    {
                        **route,
                        "file": module["file"],
                        "router_prefix": router_prefix,
                        "registration_prefix": "",
                        "final_path": join_api_path(router_prefix, route["path"]),
                        "registered": False,
                        "registered_in": None,
                    }
                )
    return resolved_routes


def analyze_version(root: Path) -> dict[str, Any]:
    inventory = file_inventory(root)
    view_root = root / "frontend" / "src" / "views"
    api_root = root / "frontend" / "src" / "api"
    views = [parse_vue_view(path, root) for path in sorted(view_root.glob("*.vue"))] if view_root.exists() else []
    frontend_apis = [parse_frontend_api(path, root) for path in sorted(api_root.glob("*.js"))] if api_root.exists() else []
    py_files = [path for path in source_files(root) if path.suffix.lower() == ".py"]
    python_modules = [parse_python(path, root) for path in py_files]
    router_registrations = resolve_router_registration_map(python_modules)
    backend_routes = [
        {**route, "file": module["file"]}
        for module in python_modules
        for route in module["routes"]
    ]
    router_definitions = [
        {**definition, "file": module["file"]}
        for module in python_modules
        for definition in module["router_definitions"]
    ]
    resolved_backend_routes = resolve_backend_routes(python_modules, router_registrations)
    orm_models = [
        {**model, "file": module["file"]}
        for module in python_modules
        for model in module["orm_models"]
    ]
    suffix_counts = Counter(item["suffix"] for item in inventory.values())
    return {
        "root": str(root.resolve()),
        "summary": {
            "source_files": len(inventory),
            "source_lines": sum(item["lines"] for item in inventory.values()),
            "source_bytes": sum(item["bytes"] for item in inventory.values()),
            "suffix_counts": dict(sorted(suffix_counts.items())),
            "vue_views": len(views),
            "vue_routes": len(parse_vue_routes(root)),
            "frontend_api_modules": len(frontend_apis),
            "python_modules": len(python_modules),
            "backend_routes": len(backend_routes),
            "router_definitions": len(router_definitions),
            "router_registrations": len(router_registrations),
            "registered_backend_routes": sum(1 for route in resolved_backend_routes if route["registered"]),
            "unregistered_backend_routes": sum(1 for route in resolved_backend_routes if not route["registered"]),
            "orm_models": len(orm_models),
            "test_files": sum(1 for path in inventory if path.startswith("tests/") and path.endswith(".py")),
        },
        "inventory": inventory,
        "vue_routes": parse_vue_routes(root),
        "views": views,
        "frontend_apis": frontend_apis,
        "python_modules": python_modules,
        "backend_routes": backend_routes,
        "router_definitions": router_definitions,
        "router_registrations": router_registrations,
        "resolved_backend_routes": resolved_backend_routes,
        "orm_models": orm_models,
    }


def compare_versions(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    before = baseline["inventory"]
    after = current["inventory"]
    before_keys = set(before)
    after_keys = set(after)
    common = before_keys & after_keys
    return {
        "unchanged": sorted(path for path in common if before[path]["sha256"] == after[path]["sha256"]),
        "modified": sorted(path for path in common if before[path]["sha256"] != after[path]["sha256"]),
        "added": sorted(after_keys - before_keys),
        "removed": sorted(before_keys - after_keys),
        "line_delta_by_file": {
            path: after[path]["lines"] - before[path]["lines"]
            for path in sorted(common)
            if after[path]["lines"] != before[path]["lines"]
        },
    }


def extract_docx(docx_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    namespaces = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    with zipfile.ZipFile(docx_path) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        relationship_map = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels.findall("pr:Relationship", namespaces)
        }
        manifest: list[dict[str, Any]] = []
        copied: dict[str, str] = {}
        for paragraph_index, paragraph in enumerate(document.findall(".//w:body/w:p", namespaces)):
            paragraph_text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespaces)).strip()
            embeds = [node.attrib.get(f"{{{namespaces['r']}}}embed") for node in paragraph.findall(".//a:blip", namespaces)]
            media: list[str] = []
            for rel_id in filter(None, embeds):
                target = relationship_map.get(rel_id)
                if not target:
                    continue
                archive_name = "word/" + target.lstrip("/")
                if archive_name not in copied:
                    source_name = Path(target).name
                    target_name = f"{len(copied) + 1:02d}_{source_name}"
                    (output_dir / target_name).write_bytes(archive.read(archive_name))
                    copied[archive_name] = target_name
                media.append(copied[archive_name])
            if paragraph_text or media:
                manifest.append(
                    {
                        "paragraph_index": paragraph_index,
                        "text": paragraph_text,
                        "media": media,
                    }
                )
    result = {"source": str(docx_path.resolve()), "media_count": len(copied), "paragraphs": manifest}
    (output_dir / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def create_contact_sheets(
    image_dir: Path, image_names: list[str], per_sheet: int = 10
) -> list[str]:
    """Create reproducible visual indexes for the extracted requirement images."""
    width, height = 1800, 1280
    margin, gap = 40, 24
    columns, rows = 2, 5
    cell_width = (width - margin * 2 - gap) // columns
    cell_height = (height - margin * 2 - gap * (rows - 1)) // rows
    font = ImageFont.load_default()
    outputs: list[str] = []
    for sheet_index, start in enumerate(range(0, len(image_names), per_sheet), 1):
        canvas = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(canvas)
        for slot, name in enumerate(image_names[start : start + per_sheet]):
            row, column = divmod(slot, columns)
            x = margin + column * (cell_width + gap)
            y = margin + row * (cell_height + gap)
            label_height = 24
            with Image.open(image_dir / name) as raw:
                image = ImageOps.exif_transpose(raw).convert("RGB")
                image.thumbnail((cell_width - 12, cell_height - label_height - 12))
                image_x = x + (cell_width - image.width) // 2
                image_y = y + label_height + (cell_height - label_height - image.height) // 2
                canvas.paste(image, (image_x, image_y))
            draw.rectangle(
                (x, y, x + cell_width, y + cell_height), outline="#CBD5E1", width=2
            )
            draw.text((x + 8, y + 6), f"{start + slot + 1:02d}  {name}", fill="#111827", font=font)
        output_name = f"contact_sheet_{sheet_index}.jpg"
        canvas.save(image_dir / output_name, "JPEG", quality=90, optimize=True)
        outputs.append(output_name)
    return outputs


def write_route_csv(path: Path, version: str, routes: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["version", "order", "path", "name", "component", "view", "guard", "roles", "course_scoped", "redirect"],
        )
        writer.writeheader()
        for route in routes:
            writer.writerow(
                {
                    "version": version,
                    "order": route["order"],
                    "path": route["path"],
                    "name": route["name"],
                    "component": route["component"],
                    "view": route["view"],
                    "guard": route["guard"],
                    "roles": ",".join(route["roles"]),
                    "course_scoped": route["course_scoped"],
                    "redirect": route["redirect"],
                }
            )


def write_backend_route_csv(path: Path, version: str, routes: list[dict[str, Any]]) -> None:
    fields = [
        "version",
        "method",
        "final_path",
        "file",
        "line",
        "function",
        "router_prefix",
        "registration_prefix",
        "registered",
        "registered_in",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for route in routes:
            writer.writerow({"version": version, **{field: route.get(field) for field in fields[1:]}})


def write_model_csv(path: Path, version: str, models: list[dict[str, Any]]) -> None:
    fields = ["version", "file", "line", "name", "table", "bases", "fields"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for model in models:
            writer.writerow(
                {
                    "version": version,
                    "file": model.get("file"),
                    "line": model.get("line"),
                    "name": model.get("name"),
                    "table": model.get("table"),
                    "bases": ", ".join(model.get("bases", [])),
                    "fields": ", ".join(model.get("fields", [])),
                }
            )


def markdown_summary(report: dict[str, Any]) -> str:
    baseline = report["baseline"]
    current = report["current"]
    diff = report["diff"]
    rows = [
        "# 双版本机器审计摘要",
        "",
        "> 本文件由 `scripts/audit_dual_version_product.py` 生成，是代码事实索引，不是产品结论。",
        "",
        "## 规模",
        "",
        "| 指标 | 7.20 基线 | 当前版本 |",
        "|---|---:|---:|",
    ]
    labels = [
        ("source_files", "纳入审计的源码/配置文件"),
        ("source_lines", "纳入审计的总行数"),
        ("vue_views", "Vue 视图"),
        ("vue_routes", "前端路由"),
        ("frontend_api_modules", "前端 API 模块"),
        ("python_modules", "Python 模块"),
        ("backend_routes", "后端路由装饰器"),
        ("router_definitions", "APIRouter 定义"),
        ("router_registrations", "include_router 注册"),
        ("registered_backend_routes", "已注册后端端点"),
        ("unregistered_backend_routes", "未注册后端端点"),
        ("orm_models", "ORM 数据模型"),
        ("test_files", "测试文件"),
    ]
    for key, label in labels:
        rows.append(f"| {label} | {baseline['summary'][key]} | {current['summary'][key]} |")
    rows.extend(
        [
            "",
            "## 文件差异",
            "",
            f"- 未变化：{len(diff['unchanged'])}",
            f"- 已修改：{len(diff['modified'])}",
            f"- 当前新增：{len(diff['added'])}",
            f"- 当前缺失：{len(diff['removed'])}",
            "",
            "## 产物",
            "",
            "- `dual_version_code_map.json`：全量机器可读代码地图。",
            "- `baseline_frontend_routes.csv`：7.20 前端路由清单。",
            "- `current_frontend_routes.csv`：当前版前端路由清单。",
            "- `baseline_backend_routes.csv` / `current_backend_routes.csv`：解析注册关系后的最终 API 路径。",
            "- `baseline_data_models.csv` / `current_data_models.csv`：ORM 数据表和字段索引。",
            "- `improvement_ideas/manifest.json`：改进想法文字与内嵌截图位置映射。",
            "- `improvement_ideas/contact_sheet_*.jpg`：改进想法参考图视觉索引。",
            "",
        ]
    )
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--ideas", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    baseline = analyze_version(args.baseline.resolve())
    current = analyze_version(args.current.resolve())
    ideas_dir = args.output / "improvement_ideas"
    if ideas_dir.exists():
        shutil.rmtree(ideas_dir)
    ideas = extract_docx(args.ideas.resolve(), ideas_dir)
    extracted_images = sorted(
        {
            image_name
            for paragraph in ideas["paragraphs"]
            for image_name in paragraph["media"]
        }
    )
    ideas["contact_sheets"] = create_contact_sheets(ideas_dir, extracted_images)
    (ideas_dir / "manifest.json").write_text(
        json.dumps(ideas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = {
        "schema_version": "1.0",
        "baseline": baseline,
        "current": current,
        "diff": compare_versions(baseline, current),
        "improvement_ideas": ideas,
    }
    (args.output / "dual_version_code_map.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_route_csv(args.output / "baseline_frontend_routes.csv", "7.20", baseline["vue_routes"])
    write_route_csv(args.output / "current_frontend_routes.csv", "current", current["vue_routes"])
    write_backend_route_csv(
        args.output / "baseline_backend_routes.csv", "7.20", baseline["resolved_backend_routes"]
    )
    write_backend_route_csv(
        args.output / "current_backend_routes.csv", "current", current["resolved_backend_routes"]
    )
    write_model_csv(args.output / "baseline_data_models.csv", "7.20", baseline["orm_models"])
    write_model_csv(args.output / "current_data_models.csv", "current", current["orm_models"])
    (args.output / "dual_version_audit_summary.md").write_text(markdown_summary(report), encoding="utf-8")
    print(json.dumps({"baseline": baseline["summary"], "current": current["summary"], "diff": {key: len(value) for key, value in report["diff"].items() if isinstance(value, (list, dict))}, "ideas_media": ideas["media_count"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Refresh the lightweight index of project-owned source and configuration."""
from __future__ import annotations

import ast
import csv
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs' / 'code-index.csv'
SOURCE_SUFFIXES = {'.py', '.js', '.ts', '.vue', '.css', '.html', '.bat', '.cmd', '.ps1', '.json', '.ini', '.toml', '.yaml', '.yml'}
ROOT_CONFIGS = {'.env.example', '.gitignore', '.gitattributes', '.dockerignore', 'Dockerfile', 'requirements.txt', 'pytest.ini'}
SKIP_DIRECTORIES = {'node_modules', 'dist', '__pycache__', '.venv', '.pytest_cache', '.git'}
ROUTE_METHODS = {'get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'websocket', 'api_route'}


def owned_files():
    for path in ROOT.iterdir():
        if path.is_file() and (path.suffix.lower() in SOURCE_SUFFIXES - {'.json'} or path.name in ROOT_CONFIGS):
            yield path, 'root'
    for group in ('app', 'frontend', 'scripts', 'tests', 'packaging'):
        for path in (ROOT / group).rglob('*'):
            relative = path.relative_to(ROOT / group)
            if any(part in SKIP_DIRECTORIES for part in relative.parts) or not path.is_file():
                continue
            if path.name == 'package-lock.json':
                continue  # Generated dependency metadata, not owned implementation.
            if path.suffix.lower() in SOURCE_SUFFIXES or path.name == '.env.runtime.template':
                yield path, group


def describe(path: Path, group: str) -> dict:
    text = path.read_text(encoding='utf-8-sig')
    classes = functions = routes = 0
    if path.suffix == '.py':
        tree = ast.parse(text, filename=str(path))
        classes = sum(isinstance(node, ast.ClassDef) for node in tree.body)
        functions = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in tree.body)
        routes = sum(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr in ROUTE_METHODS
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for decorator in node.decorator_list
        )
    elif path.suffix in {'.js', '.ts', '.vue'}:
        classes = len(re.findall(r'^\s*(?:export\s+)?class\s+\w+', text, re.MULTILINE))
        functions = len(re.findall(r'^\s*(?:export\s+)?(?:async\s+)?function\s+\w+', text, re.MULTILINE))
    return {'path': path.relative_to(ROOT).as_posix(), 'group': group, 'lines': len(text.splitlines()), 'classes': classes, 'functions': functions, 'routes': routes}


def main() -> int:
    records = []
    errors = []
    for path, group in sorted(owned_files(), key=lambda item: item[0].relative_to(ROOT).as_posix()):
        try:
            records.append(describe(path, group))
        except (SyntaxError, UnicodeError) as exc:
            errors.append(f'{path.relative_to(ROOT)}: {exc}')
    if errors:
        print('\n'.join(errors))
        return 1
    with OUTPUT.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=('path', 'group', 'lines', 'classes', 'functions', 'routes'))
        writer.writeheader()
        writer.writerows(records)
    print(f'{len(records)} files, {sum(record["lines"] for record in records)} physical lines; all Python files parsed')
    print(dict(Counter(record['group'] for record in records)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

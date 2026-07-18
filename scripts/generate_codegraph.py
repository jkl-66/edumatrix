import os
import ast
import re

class CodeGraphGenerator:
    def __init__(self, root_dir):
        self.root_dir = os.path.abspath(root_dir)
        self.modules = {}  # Rel path -> metadata
        self.dependencies = [] # list of (from_module, to_module)

    def scan(self):
        for root, dirs, files in os.walk(self.root_dir):
            # Skip hidden folders, pycaches, data, and frontend
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__' and d != 'tests' and d != 'lzz工作目标' and d != 'data' and d != 'frontend']
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, self.root_dir).replace('\\', '/')
                    
                    # Skip some scripts if they are utility
                    if rel_path.startswith('scripts/'):
                        continue
                    
                    self.analyze_file(file_path, rel_path)
        
        self.resolve_dependencies()

    def analyze_file(self, file_path, rel_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
            tree = ast.parse(code, filename=file_path)
        except Exception as e:
            print(f"Error parsing {rel_path}: {e}")
            return

        module_doc = ast.get_docstring(tree) or ""
        
        classes = []
        functions = []
        raw_imports = []

        for node in ast.iter_child_nodes(tree):
            # Extract classes
            if isinstance(node, ast.ClassDef):
                class_doc = ast.get_docstring(node) or ""
                methods = []
                for subnode in node.body:
                    if isinstance(subnode, ast.FunctionDef):
                        method_doc = ast.get_docstring(subnode) or ""
                        # Just get first line of docstring
                        short_doc = method_doc.split('\n')[0] if method_doc else ""
                        methods.append({
                            'name': subnode.name,
                            'doc': short_doc
                        })
                classes.append({
                    'name': node.name,
                    'doc': class_doc.split('\n')[0] if class_doc else "",
                    'methods': methods
                })
            
            # Extract top-level functions
            elif isinstance(node, ast.FunctionDef):
                func_doc = ast.get_docstring(node) or ""
                functions.append({
                    'name': node.name,
                    'doc': func_doc.split('\n')[0] if func_doc else ""
                })
            
            # Extract imports
            elif isinstance(node, ast.Import):
                for name in node.names:
                    raw_imports.append((None, name.name))
            elif isinstance(node, ast.ImportFrom):
                raw_imports.append((node.module, [n.name for n in node.names]))

        self.modules[rel_path] = {
            'doc': module_doc,
            'classes': classes,
            'functions': functions,
            'raw_imports': raw_imports
        }

    def resolve_dependencies(self):
        # We want to match imports to actual modules
        # Module paths: e.g. "agent_swarm" corresponds to "agent_swarm.py"
        # "app.database" corresponds to "app/database.py" or "app/database/__init__.py"
        
        module_names_to_paths = {}
        for rel_path in self.modules:
            # e.g., "agent_swarm.py" -> "agent_swarm"
            # "app/database.py" -> "app.database"
            # "app/api/stream.py" -> "app.api.stream"
            mod_name = rel_path[:-3].replace('/', '.')
            if mod_name.endswith('.__init__'):
                mod_name = mod_name[:-9]
            module_names_to_paths[mod_name] = rel_path

        for rel_path, data in self.modules.items():
            source_mod_name = rel_path[:-3].replace('/', '.')
            if source_mod_name.endswith('.__init__'):
                source_mod_name = source_mod_name[:-9]
                
            for imp_from, imp_names in data['raw_imports']:
                if imp_from is None:
                    # e.g., import agent_swarm
                    target = imp_names
                    if target in module_names_to_paths:
                        self.dependencies.append((rel_path, module_names_to_paths[target]))
                else:
                    # e.g., from app.database import init_db
                    # or from agent_swarm import EduMatrixSwarm
                    # First check if the imported module is a local file
                    if imp_from in module_names_to_paths:
                        self.dependencies.append((rel_path, module_names_to_paths[imp_from]))
                    else:
                        # Check submodules or items imported from parent
                        # e.g. from app import database
                        parts = imp_from.split('.')
                        resolved = False
                        # Try to find prefix matches
                        for i in range(len(parts), 0, -1):
                            prefix = '.'.join(parts[:i])
                            if prefix in module_names_to_paths:
                                self.dependencies.append((rel_path, module_names_to_paths[prefix]))
                                resolved = True
                                break
                        if not resolved:
                            # It might import a module from a package, e.g. from app import main
                            # if 'app' is a folder, check if there is app/main.py
                            for name in (imp_names if isinstance(imp_names, list) else [imp_names]):
                                combined = f"{imp_from}.{name}"
                                if combined in module_names_to_paths:
                                    self.dependencies.append((rel_path, module_names_to_paths[combined]))

        # De-duplicate dependencies
        self.dependencies = list(set(self.dependencies))

    def generate_markdown(self, output_file):
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as out:
            out.write("# 🗺️ EduMatrix 智教矩阵系统代码图谱 (Code Graph)\n\n")
            out.write("本项目使用 Python AST 静态分析引擎自动提取并生成了本代码图谱，清晰展示了系统的模块划分、依赖关系、类与核心方法。本设计旨在帮助评审专家及开发团队快速理解系统底层的模块拓扑结构。\n\n")
            
            # Statistics
            num_modules = len(self.modules)
            num_classes = sum(len(m['classes']) for m in self.modules.values())
            num_funcs = sum(len(m['functions']) for m in self.modules.values())
            out.write("## 📈 系统整体统计 (System Stats)\n\n")
            out.write(f"- **总模块数 (Python Files)**: {num_modules}\n")
            out.write(f"- **总定义类数 (Classes)**: {num_classes}\n")
            out.write(f"- **顶级函数数 (Functions)**: {num_funcs}\n")
            out.write(f"- **模块间显式物理依赖数 (Dependencies)**: {len(self.dependencies)}\n\n")
            
            # Module Dependency Diagram (Mermaid)
            out.write("## 🔗 模块物理依赖拓扑图 (Module Dependency Graph)\n\n")
            out.write("```mermaid\nflowchart TD\n")
            
            # Add nodes
            for rel_path in sorted(self.modules.keys()):
                label = rel_path.split('/')[-1]
                node_id = rel_path.replace('.', '_').replace('/', '_').replace('-', '_')[:-3]
                # Distinguish core files or app subfolders
                if rel_path.startswith('app/'):
                    out.write(f"    {node_id}[\"{rel_path}\"]:::appNode\n")
                else:
                    out.write(f"    {node_id}[\"{rel_path}\"]:::coreNode\n")
                    
            # Add edges
            for src, dest in sorted(self.dependencies):
                src_id = src.replace('.', '_').replace('/', '_').replace('-', '_')[:-3]
                dest_id = dest.replace('.', '_').replace('/', '_').replace('-', '_')[:-3]
                out.write(f"    {src_id} --> {dest_id}\n")
                
            out.write("\n    classDef coreNode fill:#f9f,stroke:#333,stroke-width:2px,color:#333;\n")
            out.write("    classDef appNode fill:#bbf,stroke:#333,stroke-width:1px,color:#333;\n")
            out.write("```\n\n")
            
            # Details of each module
            out.write("## 📝 模块详细字典 (Module Reference Dictionary)\n\n")
            
            # Sort modules by relative path
            root_dir_fwd = self.root_dir.replace('\\', '/')
            for rel_path in sorted(self.modules.keys()):
                data = self.modules[rel_path]
                out.write(f"### 📄 [{rel_path.split('/')[-1]}](file:///{root_dir_fwd}/{rel_path})\n\n")
                out.write(f"**文件路径**: `{rel_path}`\n\n")
                
                doc = data['doc'].strip()
                if doc:
                    out.write(f"> {doc}\n\n")
                else:
                    out.write("> *暂无详细模块级别文档注释.*\n\n")
                
                if data['classes']:
                    out.write("#### 📦 类定义 (Classes)\n\n")
                    for cls in data['classes']:
                        out.write(f"- **`class {cls['name']}`**: {cls['doc'] or '*无类文档*'}\n")
                        if cls['methods']:
                            out.write("  - **核心方法 (Methods)**:\n")
                            for method in cls['methods']:
                                out.write(f"    - `{method['name']}()`: {method['doc'] or '*无描述*'}\n")
                    out.write("\n")
                
                if data['functions']:
                    out.write("#### ⚙️ 独立函数 (Functions)\n\n")
                    for func in data['functions']:
                        out.write(f"- `{func['name']}()`: {func['doc'] or '*无描述*'}\n")
                    out.write("\n")
                
                out.write("---\n\n")
            
            print(f"Generated Markdown at {output_file}")


if __name__ == "__main__":
    import sys
    root = r"d:\project-edumatrix\edumatrix-main"
    out = os.path.join(root, "docs", "codegraph.md")
    generator = CodeGraphGenerator(root)
    generator.scan()
    generator.generate_markdown(out)

"""
Step 1: AST 静态分析器。

扫描项目 Python 文件，提取结构信息产出 skeleton.json。
纯确定性，不用 LLM。
"""

from __future__ import annotations

import ast
import fnmatch
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..models import (
    BlockKind,
    ClassInfo,
    FileInfo,
    FunctionInfo,
    PackageInfo,
    ParameterInfo,
    Skeleton,
)
from ..config import ProjectConfig


def scan_project(config: ProjectConfig) -> Skeleton:
    """对项目进行完整的静态分析，产出 Skeleton。"""
    project_root = Path(config.project_root)
    all_files: list[FileInfo] = []
    all_packages: list[PackageInfo] = []
    call_graph: dict[str, list[str]] = {}

    for source_dir in config.source_dirs:
        src_path = project_root / source_dir
        if not src_path.exists():
            continue

        # 收集所有 Python 文件
        py_files = sorted(src_path.rglob("*.py"))
        py_files = [f for f in py_files if not _is_excluded(f, project_root, config.exclude_patterns)]

        # 识别包
        packages = _find_packages(py_files, project_root, source_dir)
        all_packages.extend(packages)

        # 逐文件分析
        for py_file in py_files:
            file_info = _analyze_file(py_file, project_root, source_dir)
            if file_info:
                all_files.append(file_info)
                # 收集调用图
                _collect_calls(file_info, call_graph)

    skeleton = Skeleton(
        project_name=config.project_name,
        project_root=str(project_root),
        source_dirs=config.source_dirs,
        scan_time=datetime.now(timezone.utc).isoformat(),
        files=all_files,
        packages=all_packages,
        call_graph=call_graph,
        stats={
            "file_count": len(all_files),
            "package_count": len(all_packages),
            "function_count": sum(len(f.functions) for f in all_files),
            "class_count": sum(len(f.classes) for f in all_files),
            "total_lines": sum(f.line_count for f in all_files),
        },
    )
    return skeleton


def _is_excluded(path: Path, project_root: Path, patterns: list[str]) -> bool:
    """检查路径是否匹配排除模式。"""
    rel = str(path.relative_to(project_root))
    for pattern in patterns:
        if pattern in rel.split("/"):
            return True
        if fnmatch.fnmatch(rel, pattern):
            return True
    return False


def _find_packages(py_files: list[Path], project_root: Path, source_dir: str) -> list[PackageInfo]:
    """识别所有包含 __init__.py 的目录。"""
    packages: list[PackageInfo] = []
    seen_dirs: set[Path] = set()

    for f in py_files:
        if f.name == "__init__.py":
            pkg_dir = f.parent
            if pkg_dir in seen_dirs:
                continue
            seen_dirs.add(pkg_dir)

            rel_path = str(pkg_dir.relative_to(project_root))
            module_path = _path_to_module(rel_path, source_dir)

            # 解析 __init__.py
            init_docstring = None
            init_all = None
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
                init_docstring = ast.get_docstring(tree)
                init_all = _extract_all(tree)
            except (SyntaxError, UnicodeDecodeError):
                pass

            pkg_files = [
                str(pf.relative_to(project_root))
                for pf in py_files
                if pf.parent == pkg_dir and pf.name != "__init__.py"
            ]

            packages.append(PackageInfo(
                package_path=rel_path,
                module_path=module_path,
                init_docstring=init_docstring,
                init_all_exports=init_all,
                files=pkg_files,
            ))

    return packages


def _analyze_file(path: Path, project_root: Path, source_dir: str) -> Optional[FileInfo]:
    """分析单个 Python 文件。"""
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    rel_path = str(path.relative_to(project_root))
    module_path = _path_to_module(rel_path, source_dir)

    file_info = FileInfo(
        file_path=rel_path,
        module_path=module_path,
        docstring=ast.get_docstring(tree),
        imports=_extract_imports(tree),
        all_exports=_extract_all(tree),
        functions=[],
        classes=[],
        line_count=len(source.splitlines()),
    )

    # 提取顶层函数和类
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func_info = _extract_function(node, module_path)
            file_info.functions.append(func_info)
        elif isinstance(node, ast.ClassDef):
            class_info = _extract_class(node, module_path)
            file_info.classes.append(class_info)

    return file_info


def _extract_function(node: ast.FunctionDef | ast.AsyncFunctionDef, parent_module: str) -> FunctionInfo:
    """从 AST 节点提取函数信息。"""
    qualified_name = f"{parent_module}:{node.name}"
    params = []
    for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
        annotation = ast.unparse(arg.annotation) if arg.annotation else None
        params.append(ParameterInfo(name=arg.arg, annotation=annotation))

    return_ann = ast.unparse(node.returns) if node.returns else None
    decorators = [ast.unparse(d) for d in node.decorator_list]
    calls = _extract_calls(node)

    return FunctionInfo(
        name=node.name,
        qualified_name=qualified_name,
        kind=BlockKind.FUNCTION,
        line_start=node.lineno,
        line_end=node.end_lineno or node.lineno,
        parameters=params,
        return_annotation=return_ann,
        docstring=ast.get_docstring(node),
        decorators=decorators,
        calls=calls,
    )


def _extract_class(node: ast.ClassDef, parent_module: str) -> ClassInfo:
    """从 AST 节点提取类信息。"""
    qualified_name = f"{parent_module}:{node.name}"
    bases = [ast.unparse(b) for b in node.bases]
    decorators = [ast.unparse(d) for d in node.decorator_list]

    methods = []
    for item in node.body:
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            method = _extract_function(item, f"{parent_module}:{node.name}")
            method.kind = BlockKind.METHOD
            method.qualified_name = f"{parent_module}:{node.name}.{item.name}"
            methods.append(method)

    return ClassInfo(
        name=node.name,
        qualified_name=qualified_name,
        line_start=node.lineno,
        line_end=node.end_lineno or node.lineno,
        docstring=ast.get_docstring(node),
        bases=bases,
        methods=methods,
        decorators=decorators,
    )


def _extract_imports(tree: ast.Module) -> list[str]:
    """提取文件中的 import 语句。"""
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(f"{module}.{alias.name}")
    return imports


def _extract_all(tree: ast.Module) -> Optional[list[str]]:
    """提取 __all__ 定义。"""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, ast.List | ast.Tuple):
                        return [
                            elt.value for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        ]
    return None


def _extract_calls(node: ast.AST) -> list[str]:
    """提取函数体内的函数调用名。"""
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.append(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                # obj.method() → 记录为 method
                calls.append(child.func.attr)
    return list(set(calls))


def _collect_calls(file_info: FileInfo, call_graph: dict[str, list[str]]) -> None:
    """从 FileInfo 收集调用关系到全局调用图。"""
    for func in file_info.functions:
        if func.calls:
            call_graph[func.qualified_name] = func.calls
    for cls in file_info.classes:
        for method in cls.methods:
            if method.calls:
                call_graph[method.qualified_name] = method.calls


def _path_to_module(rel_path: str, source_dir: str) -> str:
    """将文件相对路径转换为 Python 模块路径。"""
    # 去掉 source_dir 前缀
    if rel_path.startswith(source_dir + "/"):
        rel_path = rel_path[len(source_dir) + 1:]
    elif rel_path.startswith(source_dir):
        rel_path = rel_path[len(source_dir):]

    # 去掉 .py 后缀和 __init__
    if rel_path.endswith("/__init__.py"):
        rel_path = rel_path[:-len("/__init__.py")]
    elif rel_path.endswith(".py"):
        rel_path = rel_path[:-3]

    return rel_path.replace("/", ".")

"""
Step 3b: 从注释化代码中确定性提取结构化数据到索引。

使用正则 + AST，不依赖 LLM。
"""

from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from pathlib import Path

from ..config import ProjectConfig
from ..models import AnnotationLevel, IndexEntry, ShallowIndex

# 匹配 @memory:level 标记
MEMORY_TAG_PATTERN = re.compile(r"@memory:(system|module|block)")

# 匹配字段行：FieldName: value
FIELD_PATTERN = re.compile(r"^(What|Components|DataFlow|ExternalDeps|Exposes|DependsOn|UsedBy|Input|Output|Boundary|Parent):\s*(.+)", re.MULTILINE)


def extract_index(config: ProjectConfig) -> ShallowIndex:
    """从已注释的代码中提取浅层索引。"""
    project_root = Path(config.project_root)
    index = ShallowIndex(
        project_name=config.project_name,
        extraction_time=datetime.now(timezone.utc).isoformat(),
    )

    call_graph: dict[str, list[str]] = {}

    for source_dir in config.source_dirs:
        src_path = project_root / source_dir
        if not src_path.exists():
            continue

        for py_file in sorted(src_path.rglob("*.py")):
            rel_path = str(py_file.relative_to(project_root))

            # 跳过排除模式
            skip = False
            for pattern in config.exclude_patterns:
                if pattern in rel_path.split("/"):
                    skip = True
                    break
            if skip:
                continue

            entries, calls = _extract_from_file(py_file, rel_path, source_dir)

            for entry in entries:
                if entry.level == AnnotationLevel.SYSTEM:
                    index.system_entries.append(entry)
                elif entry.level == AnnotationLevel.MODULE:
                    index.module_entries.append(entry)
                else:
                    index.block_entries.append(entry)

            call_graph.update(calls)

    index.call_graph = call_graph

    # 补充 used_by 信息（反向索引调用图）
    _populate_used_by(index)

    index.stats = {
        "system_count": len(index.system_entries),
        "module_count": len(index.module_entries),
        "block_count": len(index.block_entries),
        "total": len(index.system_entries) + len(index.module_entries) + len(index.block_entries),
    }

    return index


def _extract_from_file(
    file_path: Path, rel_path: str, source_dir: str
) -> tuple[list[IndexEntry], dict[str, list[str]]]:
    """从单个文件提取索引条目和调用关系。"""
    entries: list[IndexEntry] = []
    call_graph: dict[str, list[str]] = {}

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return entries, call_graph

    module_path = _path_to_module(rel_path, source_dir)

    # 检查模块级 docstring
    module_docstring = ast.get_docstring(tree)
    if module_docstring and MEMORY_TAG_PATTERN.search(module_docstring):
        match = MEMORY_TAG_PATTERN.search(module_docstring)
        level = AnnotationLevel(match.group(1))
        entries.append(IndexEntry(
            id=module_path,
            level=level,
            annotation=module_docstring,
            file_path=rel_path,
            line_start=1,
            line_end=_docstring_end_line(tree),
            parent_module=module_path.rsplit(".", 1)[0] if "." in module_path else None,
            depends_on=_parse_field(module_docstring, "DependsOn"),
            used_by=_parse_field(module_docstring, "UsedBy"),
        ))

    # 遍历函数和类
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            docstring = ast.get_docstring(node)
            if docstring and MEMORY_TAG_PATTERN.search(docstring):
                qualified_name = _get_qualified_name(node, tree, module_path)
                entries.append(IndexEntry(
                    id=qualified_name,
                    level=AnnotationLevel.BLOCK,
                    annotation=docstring,
                    file_path=rel_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    parent_module=module_path,
                    depends_on=_parse_field(docstring, "DependsOn"),
                ))
                # 收集调用
                calls = _extract_calls(node)
                if calls:
                    call_graph[qualified_name] = calls

        elif isinstance(node, ast.ClassDef):
            docstring = ast.get_docstring(node)
            if docstring and MEMORY_TAG_PATTERN.search(docstring):
                qualified_name = f"{module_path}:{node.name}"
                entries.append(IndexEntry(
                    id=qualified_name,
                    level=AnnotationLevel.BLOCK,
                    annotation=docstring,
                    file_path=rel_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    parent_module=module_path,
                    depends_on=_parse_field(docstring, "DependsOn"),
                ))

    return entries, call_graph


def _populate_used_by(index: ShallowIndex) -> None:
    """利用调用图填充 used_by 字段。"""
    # 建立 name → id 的映射
    all_ids = set()
    for entries in (index.system_entries, index.module_entries, index.block_entries):
        for entry in entries:
            all_ids.add(entry.id)

    # 对每个 caller，标记其 callees 的 used_by
    id_to_entry: dict[str, IndexEntry] = {}
    for entries in (index.system_entries, index.module_entries, index.block_entries):
        for entry in entries:
            id_to_entry[entry.id] = entry

    for caller, callees in index.call_graph.items():
        for callee_name in callees:
            # 尝试匹配完整 id
            for eid, entry in id_to_entry.items():
                if eid.endswith(f":{callee_name}") or eid.endswith(f".{callee_name}"):
                    if caller not in entry.used_by:
                        entry.used_by.append(caller)


def _parse_field(docstring: str, field_name: str) -> list[str]:
    """从 docstring 中解析指定字段的值为列表。"""
    for match in FIELD_PATTERN.finditer(docstring):
        if match.group(1) == field_name:
            value = match.group(2).strip()
            # 分割逗号分隔的值
            items = [v.strip() for v in value.split(",")]
            return [i for i in items if i and i != "(无)"]
    return []


def _get_qualified_name(node: ast.AST, tree: ast.Module, module_path: str) -> str:
    """获取函数/类的 qualified name。"""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        # 检查是否是类方法
        for cls_node in ast.walk(tree):
            if isinstance(cls_node, ast.ClassDef):
                for item in cls_node.body:
                    if item is node:
                        return f"{module_path}:{cls_node.name}.{node.name}"
        return f"{module_path}:{node.name}"
    elif isinstance(node, ast.ClassDef):
        return f"{module_path}:{node.name}"
    return module_path


def _extract_calls(node: ast.AST) -> list[str]:
    """提取函数内的调用名。"""
    calls = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.add(child.func.attr)
    return list(calls)


def _docstring_end_line(tree: ast.Module) -> int:
    """获取模块 docstring 的结束行。"""
    if tree.body and isinstance(tree.body[0], ast.Expr):
        return tree.body[0].end_lineno or 1
    return 1


def _path_to_module(rel_path: str, source_dir: str) -> str:
    """文件路径 → Python 模块路径。"""
    if rel_path.startswith(source_dir + "/"):
        rel_path = rel_path[len(source_dir) + 1:]

    if rel_path.endswith("/__init__.py"):
        rel_path = rel_path[:-len("/__init__.py")]
    elif rel_path.endswith(".py"):
        rel_path = rel_path[:-3]

    return rel_path.replace("/", ".")

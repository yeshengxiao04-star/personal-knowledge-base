"""
Step 3a: 将注释写回源文件。

精确插入/替换 docstring，保持代码格式不变。
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from ..models import AnnotationEntry, AnnotationLevel, AnnotationPlan

logger = logging.getLogger(__name__)


def write_annotations(plan: AnnotationPlan, project_root: Path) -> dict[str, int]:
    """将注释清单写回源文件。返回统计信息。"""
    stats = {"written": 0, "skipped": 0, "errors": 0}

    # 按文件分组
    by_file: dict[str, list[AnnotationEntry]] = {}
    for entry in plan.entries:
        if entry.action == "skip":
            stats["skipped"] += 1
            continue
        by_file.setdefault(entry.file_path, []).append(entry)

    for file_path, entries in by_file.items():
        full_path = project_root / file_path
        if not full_path.exists():
            logger.warning(f"File not found: {full_path}")
            stats["errors"] += len(entries)
            continue

        try:
            source = full_path.read_text(encoding="utf-8")
            modified = _apply_entries(source, entries)
            if modified != source:
                full_path.write_text(modified, encoding="utf-8")
                stats["written"] += sum(1 for e in entries if e.action != "skip")
            else:
                stats["skipped"] += len(entries)
        except Exception as e:
            logger.error(f"Error writing to {file_path}: {e}")
            stats["errors"] += len(entries)

    return stats


def _apply_entries(source: str, entries: list[AnnotationEntry]) -> str:
    """对单个文件应用多条注释修改。从后往前处理避免行号偏移。"""
    lines = source.splitlines(keepends=True)

    # 解析 AST 获取精确位置
    try:
        tree = ast.parse(source)
    except SyntaxError:
        logger.warning("Cannot parse file, skipping annotations")
        return source

    # 按行号从大到小排序，从后往前插入
    positioned_entries = []
    for entry in entries:
        pos = _find_insertion_point(tree, entry, lines)
        if pos is not None:
            positioned_entries.append((pos, entry))

    positioned_entries.sort(key=lambda x: x[0], reverse=True)

    for pos, entry in positioned_entries:
        lines = _insert_or_replace_docstring(lines, pos, entry, tree)

    return "".join(lines)


def _find_insertion_point(
    tree: ast.Module, entry: AnnotationEntry, lines: list[str]
) -> int | None:
    """找到注释应插入的行号（0-indexed）。"""
    if entry.target_name == "__module__":
        # 模块级 docstring：文件开头
        return _find_module_docstring_pos(tree)

    # 查找目标函数/类
    target_parts = entry.target_name.split(":")
    if len(target_parts) < 2:
        return entry.line_hint - 1 if entry.line_hint else None

    name_part = target_parts[1]  # 可能是 "ClassName.method" 或 "func_name"

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name == name_part or f"{_parent_class_name(node, tree)}.{node.name}" == name_part:
                return node.lineno - 1  # docstring 在 def 行之后
        elif isinstance(node, ast.ClassDef):
            if node.name == name_part:
                return node.lineno - 1

    return entry.line_hint - 1 if entry.line_hint else None


def _find_module_docstring_pos(tree: ast.Module) -> int:
    """找到模块 docstring 应该在的位置。"""
    # 如果已有 docstring，返回其位置
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant):
        return tree.body[0].lineno - 1
    # 跳过 shebang 和编码声明
    return 0


def _parent_class_name(func_node: ast.AST, tree: ast.Module) -> str:
    """查找函数所属的类名。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if item is func_node:
                    return node.name
    return ""


def _insert_or_replace_docstring(
    lines: list[str],
    pos: int,
    entry: AnnotationEntry,
    tree: ast.Module,
) -> list[str]:
    """在指定位置插入或替换 docstring。"""
    docstring_text = _format_docstring(entry.content, lines, pos)

    if entry.target_name == "__module__":
        # 模块级：替换已有 module docstring 或在顶部插入
        existing_end = _find_existing_docstring_end(lines, pos)
        if existing_end is not None:
            lines[pos:existing_end + 1] = [docstring_text]
        else:
            lines.insert(0, docstring_text)
    else:
        # 函数/类级：在 def/class 行之后插入或替换
        def_line_idx = pos
        body_start = def_line_idx + 1

        # 处理多行 def 语句
        while body_start < len(lines) and not lines[body_start - 1].rstrip().endswith(":"):
            body_start += 1

        # 检测已有 docstring
        existing_end = _find_existing_docstring_end(lines, body_start)
        if existing_end is not None:
            # 替换已有 docstring
            lines[body_start:existing_end + 1] = [docstring_text]
        else:
            # 在 def/class 行后插入
            lines.insert(body_start, docstring_text)

    return lines


def _find_existing_docstring_end(lines: list[str], start: int) -> int | None:
    """查找已有 docstring 的结束行（0-indexed）。返回 None 如果没有。"""
    if start >= len(lines):
        return None

    line = lines[start].strip()

    # 单行 docstring
    if (line.startswith('"""') or line.startswith("'''")) and line.count('"""') >= 2:
        return start
    if (line.startswith("'''")) and line.count("'''") >= 2:
        return start

    # 多行 docstring
    if line.startswith('"""') or line.startswith("'''"):
        quote = line[:3]
        for i in range(start + 1, min(start + 100, len(lines))):
            if quote in lines[i]:
                return i
        return None

    return None


def _format_docstring(content: str, lines: list[str], pos: int) -> str:
    """将注释内容格式化为正确缩进的 docstring。"""
    # 检测缩进
    indent = ""
    if pos < len(lines):
        line = lines[pos]
        indent = line[: len(line) - len(line.lstrip())]
        # 如果是 def/class 行，docstring 需要再缩进一级
        stripped = line.strip()
        if stripped.startswith(("def ", "async def ", "class ")):
            indent += "    "

    # 构建 docstring
    content_lines = content.splitlines()
    result_lines = [f'{indent}"""\n']
    for cl in content_lines:
        result_lines.append(f"{indent}{cl}\n")
    result_lines.append(f'{indent}"""\n')

    return "".join(result_lines)

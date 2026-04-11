"""数据模型定义。所有组件依赖此文件。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────
# 枚举
# ─────────────────────────────────────────────


class AnnotationLevel(str, Enum):
    SYSTEM = "system"
    MODULE = "module"
    BLOCK = "block"


class BlockKind(str, Enum):
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"


# ─────────────────────────────────────────────
# Step 1 产出：项目骨架 (skeleton.json)
# ─────────────────────────────────────────────


@dataclass
class ParameterInfo:
    name: str
    annotation: Optional[str] = None
    default: Optional[str] = None


@dataclass
class FunctionInfo:
    name: str
    qualified_name: str  # module.class.func 形式
    kind: BlockKind
    line_start: int
    line_end: int
    parameters: list[ParameterInfo] = field(default_factory=list)
    return_annotation: Optional[str] = None
    docstring: Optional[str] = None
    decorators: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)  # 该函数内调用的其他函数


@dataclass
class ClassInfo:
    name: str
    qualified_name: str
    line_start: int
    line_end: int
    docstring: Optional[str] = None
    bases: list[str] = field(default_factory=list)
    methods: list[FunctionInfo] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)


@dataclass
class FileInfo:
    file_path: str  # 相对于 project_root
    module_path: str  # Python 模块路径，如 src.stage2.wds_parser
    docstring: Optional[str] = None
    imports: list[str] = field(default_factory=list)  # from x import y 的完整形式
    all_exports: Optional[list[str]] = None  # __all__ 内容
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    line_count: int = 0


@dataclass
class PackageInfo:
    """一个 Python 包（含 __init__.py 的目录）。"""
    package_path: str  # 相对路径
    module_path: str  # Python 模块路径
    init_docstring: Optional[str] = None
    init_all_exports: Optional[list[str]] = None
    files: list[str] = field(default_factory=list)  # 包内文件的相对路径


@dataclass
class Skeleton:
    """Step 1 的完整产出。"""
    project_name: str
    project_root: str
    source_dirs: list[str]
    scan_time: str
    files: list[FileInfo] = field(default_factory=list)
    packages: list[PackageInfo] = field(default_factory=list)
    call_graph: dict[str, list[str]] = field(default_factory=dict)  # caller → [callees]
    stats: dict[str, int] = field(default_factory=dict)


# ─────────────────────────────────────────────
# Step 2 产出：注释修改清单
# ─────────────────────────────────────────────


@dataclass
class AnnotationEntry:
    """一条待写入的注释。"""
    file_path: str  # 相对于 project_root
    target_name: str  # qualified_name 或 "__module__" 表示模块级
    level: AnnotationLevel
    content: str  # 完整的注释文本（含 @memory: 前缀和字段）
    action: str = "insert"  # insert | replace | skip
    line_hint: Optional[int] = None  # 建议插入位置


@dataclass
class AnnotationPlan:
    """Step 2 的完整产出。"""
    project_name: str
    generation_time: str
    model_used: str
    entries: list[AnnotationEntry] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # 被跳过的 qualified names
    stats: dict[str, int] = field(default_factory=dict)


# ─────────────────────────────────────────────
# Step 3 产出：浅层索引
# ─────────────────────────────────────────────


@dataclass
class IndexEntry:
    """索引中的一条记录。主键是 id (qualified_name)。"""
    id: str  # qualified_name，稳定标识符
    level: AnnotationLevel
    annotation: str  # 完整注释文本
    file_path: str  # 相对于 project_root
    line_start: int
    line_end: int
    parent_module: Optional[str] = None
    used_by: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class ShallowIndex:
    """Step 3 的完整产出。"""
    project_name: str
    extraction_time: str
    system_entries: list[IndexEntry] = field(default_factory=list)
    module_entries: list[IndexEntry] = field(default_factory=list)
    block_entries: list[IndexEntry] = field(default_factory=list)
    call_graph: dict[str, list[str]] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)

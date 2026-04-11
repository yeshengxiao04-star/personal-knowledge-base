"""数据模型定义。所有组件依赖此文件。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TypedDict


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
# 注释类型定义（TypedDict）
# ─────────────────────────────────────────────


class SystemAnnotation(TypedDict):
    what: str
    components: list[str]
    data_flow: str
    external_deps: list[str]


class ModuleAnnotation(TypedDict):
    what: str
    exposes: list[str]
    depends_on: list[str]
    used_by: list[str]


class BlockAnnotation(TypedDict):
    what: str
    input: dict[str, str]
    output: str
    boundary: str
    parent: str


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
    calls: list[str] = field(default_factory=list)
    signature_hash: str = ""
    body_hash: str = ""
    call_hash: str = ""


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
    signature_hash: str = ""
    body_hash: str = ""
    call_hash: str = ""


@dataclass
class FileInfo:
    file_path: str
    module_path: str
    docstring: Optional[str] = None
    imports: list[str] = field(default_factory=list)
    all_exports: Optional[list[str]] = None
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    line_count: int = 0


@dataclass
class PackageInfo:
    """一个 Python 包（含 __init__.py 的目录）。"""
    package_path: str
    module_path: str
    init_docstring: Optional[str] = None
    init_all_exports: Optional[list[str]] = None
    files: list[str] = field(default_factory=list)


@dataclass
class Skeleton:
    """Step 1 的完整产出。"""
    project_name: str
    project_root: str
    source_dirs: list[str]
    scan_time: str
    files: list[FileInfo] = field(default_factory=list)
    packages: list[PackageInfo] = field(default_factory=list)
    call_graph: dict[str, list[str]] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)


# ─────────────────────────────────────────────
# Step 2 产出：注释存储
# ─────────────────────────────────────────────


@dataclass
class AnnotationEntry:
    """一条注释。"""
    qualified_name: str
    level: AnnotationLevel
    annotation: dict  # SystemAnnotation | ModuleAnnotation | BlockAnnotation


@dataclass
class AnnotationStore:
    """Step 2 的完整产出。"""
    project_name: str
    generation_time: str
    model_used: str
    entries: dict[str, AnnotationEntry] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


# ─────────────────────────────────────────────
# Step 3 产出：浅层索引
# ─────────────────────────────────────────────


@dataclass
class IndexEntry:
    """索引中的一条记录。主键是 id (qualified_name)。"""
    id: str
    level: AnnotationLevel
    file_path: str
    line_start: int
    line_end: int
    parent_module: Optional[str] = None
    signature_hash: str = ""
    body_hash: str = ""
    call_hash: str = ""
    annotation: Optional[dict] = None
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

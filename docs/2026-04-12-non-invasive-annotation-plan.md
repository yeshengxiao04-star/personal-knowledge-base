# 非侵入式注释架构改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 code_memory 的 Init 管线从侵入式（注释写回源码）改为非侵入式（注释外存 JSON，skeleton 做锚定）。

**Architecture:** 三步管线保持：scan → annotate → index。Scanner 新增 hash 计算；Annotator 输出结构化 JSON 而非 docstring 文本；Writer 删除；Extractor 替换为纯合并的 Indexer。

**Tech Stack:** Python 3.10+, stdlib (ast, hashlib, json, dataclasses, typing), PyYAML, OpenAI SDK

---

## File Structure

**Create:**
- `code_memory/init/indexer.py` — Step 3: 合并 skeleton + annotations → index
- `tests/__init__.py` — 测试包
- `tests/test_models.py` — 模型测试
- `tests/test_scanner.py` — Hash 计算测试
- `tests/test_annotator.py` — JSON 解析测试
- `tests/test_indexer.py` — 合并逻辑测试

**Modify:**
- `code_memory/models.py` — 新增 hash 字段、TypedDict、重定义 AnnotationEntry/Store/IndexEntry
- `code_memory/init/scanner.py` — 新增 hash 计算
- `code_memory/init/annotator.py` — 输出 JSON、使用 AnnotationStore
- `code_memory/llm/prompts/system_annotation.py` — 要求 JSON 输出
- `code_memory/llm/prompts/module_annotation.py` — 要求 JSON 输出
- `code_memory/llm/prompts/block_annotation.py` — 要求 JSON 输出
- `code_memory/cli.py` — 移除 write 步骤，重命名 extract→index，更新管线

**Delete:**
- `code_memory/init/writer.py`
- `code_memory/init/extractor.py`

---

### Task 1: 更新数据模型

**Files:**
- Modify: `code_memory/models.py`
- Create: `tests/__init__.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: 创建测试目录和基础测试**

```bash
mkdir -p tests
touch tests/__init__.py
```

`tests/test_models.py`:
```python
"""数据模型测试。"""

from code_memory.models import (
    AnnotationEntry,
    AnnotationLevel,
    AnnotationStore,
    BlockKind,
    ClassInfo,
    FunctionInfo,
    IndexEntry,
    ParameterInfo,
)


def test_function_info_has_hash_fields():
    fi = FunctionInfo(
        name="foo", qualified_name="mod:foo",
        kind=BlockKind.FUNCTION, line_start=1, line_end=5,
    )
    assert fi.signature_hash == ""
    assert fi.body_hash == ""
    assert fi.call_hash == ""


def test_class_info_has_hash_fields():
    ci = ClassInfo(
        name="Bar", qualified_name="mod:Bar",
        line_start=1, line_end=20,
    )
    assert ci.signature_hash == ""
    assert ci.body_hash == ""
    assert ci.call_hash == ""


def test_annotation_entry_new_shape():
    entry = AnnotationEntry(
        qualified_name="mod:foo",
        level=AnnotationLevel.BLOCK,
        annotation={"what": "does stuff", "input": {}, "output": "None", "boundary": "", "parent": "mod"},
    )
    assert entry.qualified_name == "mod:foo"
    assert isinstance(entry.annotation, dict)
    assert entry.annotation["what"] == "does stuff"


def test_annotation_store_dict_entries():
    store = AnnotationStore(
        project_name="test", generation_time="now", model_used="test-model",
    )
    entry = AnnotationEntry(
        qualified_name="mod:foo", level=AnnotationLevel.BLOCK,
        annotation={"what": "test"},
    )
    store.entries["mod:foo"] = entry
    assert "mod:foo" in store.entries
    assert store.entries["mod:foo"].annotation["what"] == "test"


def test_index_entry_has_hash_and_dict_annotation():
    ie = IndexEntry(
        id="mod:foo", level=AnnotationLevel.BLOCK,
        file_path="src/mod.py", line_start=10, line_end=20,
        signature_hash="abcd1234abcd1234",
        body_hash="efgh5678efgh5678",
        call_hash="ijkl9012ijkl9012",
        annotation={"what": "test", "input": {}, "output": "int", "boundary": "", "parent": "mod"},
    )
    assert ie.signature_hash == "abcd1234abcd1234"
    assert isinstance(ie.annotation, dict)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/mac/Documents/projects/个人知识库 && python -m pytest tests/test_models.py -v`
Expected: FAIL — AnnotationEntry 构造参数不匹配，IndexEntry 缺少 hash 字段

- [ ] **Step 3: 修改 models.py**

`code_memory/models.py` — 完整替换 Step 2 和 Step 3 的模型定义：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/mac/Documents/projects/个人知识库 && python -m pytest tests/test_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: 提交**

```bash
git add code_memory/models.py tests/__init__.py tests/test_models.py
git commit -m "refactor(models): add hash fields, TypedDicts, AnnotationStore for non-invasive annotations"
```

---

### Task 2: Scanner 增加 Hash 计算

**Files:**
- Modify: `code_memory/init/scanner.py`
- Create: `tests/test_scanner.py`

- [ ] **Step 1: 编写 hash 计算测试**

`tests/test_scanner.py`:
```python
"""Scanner hash 计算测试。"""

from code_memory.models import BlockKind, FunctionInfo, ClassInfo, ParameterInfo


def test_compute_signature_hash_deterministic():
    from code_memory.init.scanner import _compute_signature_hash
    fi = FunctionInfo(
        name="foo", qualified_name="mod:foo", kind=BlockKind.FUNCTION,
        line_start=1, line_end=5,
        parameters=[ParameterInfo(name="x", annotation="int"), ParameterInfo(name="y", annotation="str")],
        return_annotation="bool",
    )
    h1 = _compute_signature_hash(fi)
    h2 = _compute_signature_hash(fi)
    assert h1 == h2
    assert len(h1) == 16
    assert all(c in "0123456789abcdef" for c in h1)


def test_compute_signature_hash_differs_on_param_change():
    from code_memory.init.scanner import _compute_signature_hash
    fi1 = FunctionInfo(
        name="foo", qualified_name="mod:foo", kind=BlockKind.FUNCTION,
        line_start=1, line_end=5,
        parameters=[ParameterInfo(name="x", annotation="int")],
    )
    fi2 = FunctionInfo(
        name="foo", qualified_name="mod:foo", kind=BlockKind.FUNCTION,
        line_start=1, line_end=5,
        parameters=[ParameterInfo(name="x", annotation="str")],
    )
    assert _compute_signature_hash(fi1) != _compute_signature_hash(fi2)


def test_compute_body_hash_ignores_comments_and_blanks():
    from code_memory.init.scanner import _compute_body_hash
    lines_clean = ["def foo(x):", "    return x + 1"]
    lines_commented = ["def foo(x):", "    # a comment", "    return x + 1", ""]
    h1 = _compute_body_hash(lines_clean, 1, 2)
    h2 = _compute_body_hash(lines_commented, 1, 4)
    assert h1 == h2
    assert len(h1) == 16


def test_compute_body_hash_differs_on_code_change():
    from code_memory.init.scanner import _compute_body_hash
    lines1 = ["def foo(x):", "    return x + 1"]
    lines2 = ["def foo(x):", "    return x + 2"]
    assert _compute_body_hash(lines1, 1, 2) != _compute_body_hash(lines2, 1, 2)


def test_compute_call_hash_order_independent():
    from code_memory.init.scanner import _compute_call_hash
    h1 = _compute_call_hash(["bar", "baz", "qux"])
    h2 = _compute_call_hash(["qux", "bar", "baz"])
    assert h1 == h2
    assert len(h1) == 16


def test_compute_call_hash_empty():
    from code_memory.init.scanner import _compute_call_hash
    h = _compute_call_hash([])
    assert len(h) == 16


def test_compute_class_signature_hash():
    from code_memory.init.scanner import _compute_class_signature_hash
    method = FunctionInfo(
        name="do", qualified_name="mod:Cls.do", kind=BlockKind.METHOD,
        line_start=3, line_end=5, signature_hash="abcd1234abcd1234",
    )
    cls = ClassInfo(
        name="Cls", qualified_name="mod:Cls",
        line_start=1, line_end=10, bases=["Base"], methods=[method],
    )
    h = _compute_class_signature_hash(cls)
    assert len(h) == 16


def test_scan_project_populates_hashes(tmp_path):
    """扫描真实文件后，FunctionInfo 应该有非空 hash。"""
    from code_memory.init.scanner import scan_project
    from code_memory.config import ProjectConfig

    # 创建一个简单的 Python 文件
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "example.py").write_text(
        "def greet(name: str) -> str:\n"
        "    return f'Hello, {name}'\n"
    )

    config = ProjectConfig(
        project_name="test", project_root=str(tmp_path), source_dirs=["src"],
    )
    skeleton = scan_project(config)

    assert len(skeleton.files) >= 1
    funcs = [f for fi in skeleton.files for f in fi.functions]
    assert len(funcs) == 1
    assert funcs[0].signature_hash != ""
    assert funcs[0].body_hash != ""
    assert funcs[0].call_hash != ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/mac/Documents/projects/个人知识库 && python -m pytest tests/test_scanner.py -v`
Expected: FAIL — `_compute_signature_hash` 等函数不存在

- [ ] **Step 3: 在 scanner.py 中实现 hash 函数**

在 `code_memory/init/scanner.py` 顶部 import 中添加：

```python
import hashlib
```

在文件末尾（`_path_to_module` 之后）添加 hash 计算函数：

```python
def _compute_signature_hash(func: FunctionInfo) -> str:
    """计算函数签名 hash。"""
    params_str = ",".join(
        f"{p.name}:{p.annotation or ''}" for p in func.parameters
    )
    canonical = f"{func.name}({params_str})->{func.return_annotation or ''}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _compute_class_signature_hash(cls: ClassInfo) -> str:
    """计算类签名 hash。"""
    bases = ",".join(cls.bases)
    method_sigs = ",".join(sorted(m.signature_hash for m in cls.methods))
    canonical = f"{cls.name}({bases})[{method_sigs}]"
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _compute_body_hash(source_lines: list[str], line_start: int, line_end: int) -> str:
    """计算代码体 hash（去注释去空行）。"""
    body = source_lines[line_start - 1:line_end]
    stripped = [l for l in body if l.strip() and not l.strip().startswith("#")]
    content = "\n".join(stripped)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _compute_call_hash(calls: list[str]) -> str:
    """计算调用列表 hash。"""
    content = ",".join(sorted(calls))
    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

- [ ] **Step 4: 在 `_analyze_file` 中集成 hash 计算**

在 `_analyze_file` 函数中，`return file_info` 之前插入 hash 计算：

```python
    # 提取顶层函数和类
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func_info = _extract_function(node, module_path)
            file_info.functions.append(func_info)
        elif isinstance(node, ast.ClassDef):
            class_info = _extract_class(node, module_path)
            file_info.classes.append(class_info)

    # --- 新增：计算 hash ---
    source_lines = source.splitlines()
    for func in file_info.functions:
        func.signature_hash = _compute_signature_hash(func)
        func.body_hash = _compute_body_hash(source_lines, func.line_start, func.line_end)
        func.call_hash = _compute_call_hash(func.calls)

    for cls in file_info.classes:
        for method in cls.methods:
            method.signature_hash = _compute_signature_hash(method)
            method.body_hash = _compute_body_hash(source_lines, method.line_start, method.line_end)
            method.call_hash = _compute_call_hash(method.calls)
        cls.body_hash = _compute_body_hash(source_lines, cls.line_start, cls.line_end)
        cls.call_hash = _compute_call_hash(
            list(set(c for m in cls.methods for c in m.calls))
        )
        cls.signature_hash = _compute_class_signature_hash(cls)
    # --- 新增结束 ---

    return file_info
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd /Users/mac/Documents/projects/个人知识库 && python -m pytest tests/test_scanner.py -v`
Expected: ALL PASS

- [ ] **Step 6: 提交**

```bash
git add code_memory/init/scanner.py tests/test_scanner.py
git commit -m "feat(scanner): add signature/body/call hash computation"
```

---

### Task 3: 更新 Prompt 模板

**Files:**
- Modify: `code_memory/llm/prompts/system_annotation.py`
- Modify: `code_memory/llm/prompts/module_annotation.py`
- Modify: `code_memory/llm/prompts/block_annotation.py`

- [ ] **Step 1: 更新 system_annotation.py**

完整替换 `code_memory/llm/prompts/system_annotation.py`：

```python
"""系统级注释生成的 Prompt 模板。"""

SYSTEM_PROMPT = """\
你是一个代码分析专家。你的任务是为一个软件项目生成系统级注释。

系统级注释描述整个项目的全局视图。

输出要求：只输出一个 JSON 对象，包含以下字段：
- "what": string — 这个系统是什么、做什么（一句话）
- "components": list[string] — 主要组成模块列表
- "data_flow": string — 数据从输入到输出的主要流转路径
- "external_deps": list[string] — 外部依赖列表（API、服务、数据库等）

示例输出：
{"what": "端到端编译工具链", "components": ["stage0", "stage1"], "data_flow": "NL → DSL", "external_deps": ["LLM API"]}

规则：
1. 只描述事实（代码是什么、做什么），不加入决策理由或评价
2. 自足性：读者不看代码也能理解
3. 简洁：每个字段 1-3 行
4. 只输出 JSON 对象，不要 markdown 包裹、不要解释、不要换行前缀
"""

USER_PROMPT_TEMPLATE = """\
以下是项目 "{project_name}" 的完整骨架信息：

## 包结构
{packages_summary}

## 文件列表及顶层函数/类
{files_summary}

## 模块间依赖（import 关系）
{import_summary}

请为这个项目生成系统级注释。只输出 JSON 对象。
"""
```

- [ ] **Step 2: 更新 module_annotation.py**

完整替换 `code_memory/llm/prompts/module_annotation.py`：

```python
"""模块级注释生成的 Prompt 模板。"""

SYSTEM_PROMPT = """\
你是一个代码分析专家。你的任务是为一个 Python 模块（包）生成模块级注释。

输出要求：只输出一个 JSON 对象，包含以下字段：
- "what": string — 这个模块做什么（一句话）
- "exposes": list[string] — 对外暴露的主要接口（函数名/类名）
- "depends_on": list[string] — 依赖的其他内部模块
- "used_by": list[string] — 被哪些模块使用

示例输出：
{"what": "WDS → IR 转换", "exposes": ["compile_wds_to_ir"], "depends_on": ["models.wds"], "used_by": ["stage3"]}

规则：
1. 只描述事实，不加入决策理由
2. 自足性：不看代码也能理解这个模块的定位
3. exposes 只列主要公开接口，不列内部辅助函数
4. depends_on 和 used_by 只列同项目内的模块，不列标准库
5. 只输出 JSON 对象，不要 markdown 包裹、不要解释
"""

USER_PROMPT_TEMPLATE = """\
## 项目系统级上下文
{system_annotation}

## 当前模块: {module_path}

### 模块内文件
{module_files}

### 模块公开接口 (__all__ 或公开函数/类)
{public_api}

### 模块导入关系
{imports}

### 被其他模块引用情况
{used_by_info}

请为模块 "{module_path}" 生成模块级注释。只输出 JSON 对象。
"""
```

- [ ] **Step 3: 更新 block_annotation.py**

完整替换 `code_memory/llm/prompts/block_annotation.py`：

```python
"""块级注释生成的 Prompt 模板。"""

SYSTEM_PROMPT = """\
你是一个代码分析专家。你的任务是为 Python 函数或类生成块级注释。

输出要求：只输出一个 JSON 对象，包含以下字段：
- "what": string — 这个函数/类做什么（一句话）
- "input": object — 输入参数映射，key 为参数名，value 为描述
- "output": string — 返回值描述
- "boundary": string — 前置假设、不处理的情况、失效条件
- "parent": string — 所属模块路径

示例输出：
{"what": "解析 WDS YAML", "input": {"yaml_str": "原始 YAML", "strict": "严格模式"}, "output": "WDSWorkflow", "boundary": "YAML 格式错误时抛异常", "parent": "src.stage2"}

规则：
1. 只描述事实，不加入决策理由或设计评价
2. 自足性：不看函数体也能理解这个函数做什么
3. boundary 很重要：明确什么情况下不适用、什么前提条件必须满足
4. 如果函数非常简单（getter/setter/直接委托），input 可以为空对象 {}
5. 只输出 JSON 对象，不要 markdown 包裹、不要解释
"""

USER_PROMPT_TEMPLATE = """\
## 所属模块上下文
{module_annotation}

## 当前函数/类: {qualified_name}

### 签名
{signature}

### 完整代码
```python
{source_code}
```

### 该函数内部调用了
{calls}

请为 "{qualified_name}" 生成块级注释。只输出 JSON 对象。
"""
```

- [ ] **Step 4: 提交**

```bash
git add code_memory/llm/prompts/system_annotation.py code_memory/llm/prompts/module_annotation.py code_memory/llm/prompts/block_annotation.py
git commit -m "refactor(prompts): request JSON output instead of @memory text format"
```

---

### Task 4: 改造 Annotator

**Files:**
- Modify: `code_memory/init/annotator.py`
- Create: `tests/test_annotator.py`

- [ ] **Step 1: 编写 JSON 解析测试**

`tests/test_annotator.py`:
```python
"""Annotator JSON 解析测试。"""

from code_memory.init.annotator import _parse_json_response


def test_parse_clean_json():
    raw = '{"what": "does stuff", "input": {}, "output": "None", "boundary": "", "parent": "mod"}'
    result = _parse_json_response(raw)
    assert result is not None
    assert result["what"] == "does stuff"


def test_parse_json_with_markdown_wrapper():
    raw = '```json\n{"what": "does stuff"}\n```'
    result = _parse_json_response(raw)
    assert result is not None
    assert result["what"] == "does stuff"


def test_parse_json_with_preamble():
    raw = 'Here is the annotation:\n{"what": "does stuff", "components": ["a"]}'
    result = _parse_json_response(raw)
    assert result is not None
    assert result["what"] == "does stuff"


def test_parse_invalid_json_returns_none():
    raw = "This is not JSON at all"
    result = _parse_json_response(raw)
    assert result is None


def test_parse_json_with_trailing_comma():
    """LLM 常见错误：JSON 末尾多余逗号。"""
    raw = '{"what": "stuff", "output": "None",}'
    result = _parse_json_response(raw)
    # 可能解析失败，取决于实现的容错程度
    # 至少不应崩溃
    assert result is None or isinstance(result, dict)


def test_parse_empty_returns_none():
    assert _parse_json_response("") is None
    assert _parse_json_response("   ") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/mac/Documents/projects/个人知识库 && python -m pytest tests/test_annotator.py -v`
Expected: FAIL — `_parse_json_response` 不存在

- [ ] **Step 3: 重写 annotator.py**

完整替换 `code_memory/init/annotator.py`：

```python
"""
Step 2: LLM 注释生成编排器。

读取 skeleton.json，从粗到细调用 LLM 生成三层注释。
产出注释存储 (AnnotationStore)，结构化 JSON 格式。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import ProjectConfig
from ..llm.client import LLMClient
from ..llm.prompts import system_annotation, module_annotation, block_annotation
from ..models import (
    AnnotationEntry,
    AnnotationLevel,
    AnnotationStore,
    ClassInfo,
    FileInfo,
    FunctionInfo,
    PackageInfo,
    Skeleton,
)

logger = logging.getLogger(__name__)


def generate_annotations(
    skeleton: Skeleton,
    config: ProjectConfig,
    llm_client: Optional[LLMClient] = None,
    existing: Optional[AnnotationStore] = None,
) -> AnnotationStore:
    """生成完整的注释存储。从系统→模块→块逐层生成。"""
    if llm_client is None:
        llm_client = LLMClient(config.llm)

    store = AnnotationStore(
        project_name=skeleton.project_name,
        generation_time=datetime.now(timezone.utc).isoformat(),
        model_used=config.llm.model,
    )

    # Step 2.1: 系统级注释
    logger.info("Generating system-level annotation...")
    system_entry = _generate_system_annotation(skeleton, llm_client, config, existing)
    if system_entry:
        store.entries[system_entry.qualified_name] = system_entry

    # Step 2.2: 模块级注释
    logger.info("Generating module-level annotations...")
    system_context = json.dumps(system_entry.annotation, ensure_ascii=False, indent=2) if system_entry else ""
    for pkg in skeleton.packages:
        entry = _generate_module_annotation(
            pkg, skeleton, system_context, llm_client, config, existing
        )
        if entry:
            store.entries[entry.qualified_name] = entry

    # Step 2.3: 块级注释
    logger.info("Generating block-level annotations...")
    for file_info in skeleton.files:
        _generate_block_annotations(
            file_info, skeleton, store, llm_client, config, existing
        )

    store.stats = {
        "system_count": sum(1 for e in store.entries.values() if e.level == AnnotationLevel.SYSTEM),
        "module_count": sum(1 for e in store.entries.values() if e.level == AnnotationLevel.MODULE),
        "block_count": sum(1 for e in store.entries.values() if e.level == AnnotationLevel.BLOCK),
        "skipped_count": len(store.skipped),
    }

    return store


def _generate_system_annotation(
    skeleton: Skeleton,
    llm_client: LLMClient,
    config: ProjectConfig,
    existing: Optional[AnnotationStore],
) -> Optional[AnnotationEntry]:
    """生成系统级注释。"""
    system_qname = _find_system_qname(skeleton)

    if existing and not config.annotation.overwrite_existing:
        if system_qname in existing.entries:
            return existing.entries[system_qname]

    packages_summary = _format_packages_summary(skeleton.packages)
    files_summary = _format_files_summary(skeleton.files[:50])
    import_summary = _format_import_summary(skeleton)

    user_prompt = system_annotation.USER_PROMPT_TEMPLATE.format(
        project_name=skeleton.project_name,
        packages_summary=packages_summary,
        files_summary=files_summary,
        import_summary=import_summary,
    )

    response = llm_client.generate(
        system_prompt=system_annotation.SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    annotation = _parse_json_response(response.content)
    if not annotation:
        logger.warning("Failed to parse system annotation JSON")
        return None

    return AnnotationEntry(
        qualified_name=system_qname,
        level=AnnotationLevel.SYSTEM,
        annotation=annotation,
    )


def _generate_module_annotation(
    pkg: PackageInfo,
    skeleton: Skeleton,
    system_context: str,
    llm_client: LLMClient,
    config: ProjectConfig,
    existing: Optional[AnnotationStore],
) -> Optional[AnnotationEntry]:
    """为一个包生成模块级注释。"""
    if existing and not config.annotation.overwrite_existing:
        if pkg.module_path in existing.entries:
            return existing.entries[pkg.module_path]

    module_files = _get_module_files(pkg, skeleton)
    public_api = _get_public_api(pkg, skeleton)
    imports = _get_module_imports(pkg, skeleton)
    used_by = _get_used_by(pkg.module_path, skeleton)

    user_prompt = module_annotation.USER_PROMPT_TEMPLATE.format(
        system_annotation=system_context,
        module_path=pkg.module_path,
        module_files=module_files,
        public_api=public_api,
        imports=imports,
        used_by_info=used_by,
    )

    response = llm_client.generate(
        system_prompt=module_annotation.SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    annotation = _parse_json_response(response.content)
    if not annotation:
        logger.warning(f"Failed to parse module annotation JSON for {pkg.module_path}")
        return None

    return AnnotationEntry(
        qualified_name=pkg.module_path,
        level=AnnotationLevel.MODULE,
        annotation=annotation,
    )


def _generate_block_annotations(
    file_info: FileInfo,
    skeleton: Skeleton,
    store: AnnotationStore,
    llm_client: LLMClient,
    config: ProjectConfig,
    existing: Optional[AnnotationStore],
) -> None:
    """为文件中的函数和类生成块级注释。"""
    parts = file_info.module_path.rsplit(".", 1)
    parent_module = parts[0] if len(parts) > 1 else file_info.module_path

    # 获取模块注释作为上下文
    module_entry = store.entries.get(parent_module)
    module_context = json.dumps(module_entry.annotation, ensure_ascii=False, indent=2) if module_entry else ""

    project_root = Path(skeleton.project_root)

    for func in file_info.functions:
        entry = _generate_single_block(
            func, file_info, module_context, project_root, llm_client, config, existing
        )
        if entry:
            store.entries[entry.qualified_name] = entry
        elif func.qualified_name:
            store.skipped.append(func.qualified_name)

    for cls in file_info.classes:
        cls_entry = _generate_class_block(
            cls, file_info, module_context, project_root, llm_client, config, existing
        )
        if cls_entry:
            store.entries[cls_entry.qualified_name] = cls_entry

        for method in cls.methods:
            if method.name.startswith("_") and method.name != "__init__":
                store.skipped.append(method.qualified_name)
                continue
            entry = _generate_single_block(
                method, file_info, module_context, project_root, llm_client, config, existing
            )
            if entry:
                store.entries[entry.qualified_name] = entry
            else:
                store.skipped.append(method.qualified_name)


def _generate_single_block(
    func: FunctionInfo,
    file_info: FileInfo,
    module_context: str,
    project_root: Path,
    llm_client: LLMClient,
    config: ProjectConfig,
    existing: Optional[AnnotationStore],
) -> Optional[AnnotationEntry]:
    """为单个函数生成块级注释。"""
    func_lines = func.line_end - func.line_start + 1
    if func_lines < config.annotation.min_function_lines:
        return None

    if func.name.startswith("_") and func.name != "__init__":
        return None

    if existing and not config.annotation.overwrite_existing:
        if func.qualified_name in existing.entries:
            return existing.entries[func.qualified_name]

    source_code = _read_source_range(project_root / file_info.file_path, func.line_start, func.line_end)
    signature = _format_signature(func)
    calls = ", ".join(func.calls[:20]) if func.calls else "(无)"

    user_prompt = block_annotation.USER_PROMPT_TEMPLATE.format(
        module_annotation=module_context,
        qualified_name=func.qualified_name,
        signature=signature,
        source_code=source_code,
        calls=calls,
    )

    response = llm_client.generate(
        system_prompt=block_annotation.SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    annotation = _parse_json_response(response.content)
    if not annotation:
        logger.warning(f"Failed to parse block annotation JSON for {func.qualified_name}")
        return None

    return AnnotationEntry(
        qualified_name=func.qualified_name,
        level=AnnotationLevel.BLOCK,
        annotation=annotation,
    )


def _generate_class_block(
    cls: ClassInfo,
    file_info: FileInfo,
    module_context: str,
    project_root: Path,
    llm_client: LLMClient,
    config: ProjectConfig,
    existing: Optional[AnnotationStore],
) -> Optional[AnnotationEntry]:
    """为类生成块级注释。"""
    if existing and not config.annotation.overwrite_existing:
        if cls.qualified_name in existing.entries:
            return existing.entries[cls.qualified_name]

    source_code = _read_source_range(
        project_root / file_info.file_path, cls.line_start, min(cls.line_start + 30, cls.line_end)
    )
    methods_list = ", ".join(m.name for m in cls.methods[:15])

    user_prompt = block_annotation.USER_PROMPT_TEMPLATE.format(
        module_annotation=module_context,
        qualified_name=cls.qualified_name,
        signature=f"class {cls.name}({', '.join(cls.bases)})" if cls.bases else f"class {cls.name}",
        source_code=source_code,
        calls=f"Methods: {methods_list}" if methods_list else "(无方法)",
    )

    response = llm_client.generate(
        system_prompt=block_annotation.SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    annotation = _parse_json_response(response.content)
    if not annotation:
        logger.warning(f"Failed to parse class annotation JSON for {cls.qualified_name}")
        return None

    return AnnotationEntry(
        qualified_name=cls.qualified_name,
        level=AnnotationLevel.BLOCK,
        annotation=annotation,
    )


# ─────────────────────────────────────────────
# JSON 解析
# ─────────────────────────────────────────────


def _parse_json_response(raw: str) -> Optional[dict]:
    """从 LLM 输出中提取 JSON 对象。容忍 markdown 包裹和前缀文字。"""
    raw = raw.strip()
    if not raw:
        return None

    # 去掉 markdown code block
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    # 尝试直接解析
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 对象
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            result = json.loads(raw[start:end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────


def _find_system_qname(skeleton: Skeleton) -> str:
    """找到系统级注释的 qualified name。"""
    if skeleton.packages:
        top_level = [p for p in skeleton.packages if "." not in p.module_path]
        if top_level:
            return top_level[0].module_path
        return skeleton.packages[0].module_path
    return skeleton.project_name


def _format_packages_summary(packages: list[PackageInfo]) -> str:
    lines = []
    for pkg in packages:
        files_str = ", ".join(Path(f).name for f in pkg.files[:10])
        lines.append(f"- {pkg.module_path}: [{files_str}]")
    return "\n".join(lines)


def _format_files_summary(files: list[FileInfo]) -> str:
    lines = []
    for f in files:
        funcs = [fn.name for fn in f.functions[:5]]
        classes = [c.name for c in f.classes[:3]]
        items = funcs + classes
        lines.append(f"- {f.module_path}: {', '.join(items) if items else '(空)'}")
    return "\n".join(lines)


def _format_import_summary(skeleton: Skeleton) -> str:
    """生成模块间导入关系摘要。"""
    module_paths = {f.module_path for f in skeleton.files}
    import_map: dict[str, set[str]] = {}

    for f in skeleton.files:
        for imp in f.imports:
            for mp in module_paths:
                if imp.startswith(mp) or mp.startswith(imp.rsplit(".", 1)[0]):
                    import_map.setdefault(imp.rsplit(".", 1)[0], set()).add(f.module_path)
                    break

    lines = []
    for target, importers in sorted(import_map.items())[:30]:
        lines.append(f"- {target} ← [{', '.join(sorted(importers)[:5])}]")
    return "\n".join(lines) if lines else "(无内部依赖)"


def _get_module_files(pkg: PackageInfo, skeleton: Skeleton) -> str:
    lines = []
    for f in skeleton.files:
        if f.file_path.startswith(pkg.package_path + "/"):
            funcs = ", ".join(fn.name for fn in f.functions[:5])
            lines.append(f"  - {Path(f.file_path).name}: {funcs}")
    return "\n".join(lines) if lines else "(空包)"


def _get_public_api(pkg: PackageInfo, skeleton: Skeleton) -> str:
    if pkg.init_all_exports:
        return ", ".join(pkg.init_all_exports)
    public = []
    for f in skeleton.files:
        if f.file_path.startswith(pkg.package_path + "/"):
            for fn in f.functions:
                if not fn.name.startswith("_"):
                    public.append(fn.name)
    return ", ".join(public[:20]) if public else "(无公开接口)"


def _get_module_imports(pkg: PackageInfo, skeleton: Skeleton) -> str:
    imports: set[str] = set()
    for f in skeleton.files:
        if f.file_path.startswith(pkg.package_path + "/"):
            for imp in f.imports:
                if not imp.startswith(pkg.module_path):
                    imports.add(imp)
    stdlib_prefixes = (
        "os", "sys", "pathlib", "typing", "dataclass", "enum", "json",
        "re", "ast", "datetime", "collections", "abc", "functools", "logging",
    )
    internal = [i for i in sorted(imports) if not i.startswith(stdlib_prefixes)]
    return ", ".join(internal[:20]) if internal else "(无内部依赖)"


def _get_used_by(module_path: str, skeleton: Skeleton) -> str:
    users: set[str] = set()
    for f in skeleton.files:
        if f.module_path == module_path:
            continue
        for imp in f.imports:
            if imp.startswith(module_path):
                users.add(f.module_path)
    return ", ".join(sorted(users)[:10]) if users else "(未被引用)"


def _read_source_range(file_path: Path, start: int, end: int) -> str:
    """读取文件指定行范围的源码。"""
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[start - 1:end])
    except (OSError, IndexError):
        return "(无法读取源码)"


def _format_signature(func: FunctionInfo) -> str:
    params = []
    for p in func.parameters:
        s = p.name
        if p.annotation:
            s += f": {p.annotation}"
        if p.default:
            s += f" = {p.default}"
        params.append(s)
    ret = f" -> {func.return_annotation}" if func.return_annotation else ""
    return f"def {func.name}({', '.join(params)}){ret}"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/mac/Documents/projects/个人知识库 && python -m pytest tests/test_annotator.py tests/test_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: 提交**

```bash
git add code_memory/init/annotator.py tests/test_annotator.py
git commit -m "refactor(annotator): output structured JSON via AnnotationStore"
```

---

### Task 5: 创建 Indexer

**Files:**
- Create: `code_memory/init/indexer.py`
- Create: `tests/test_indexer.py`

- [ ] **Step 1: 编写 indexer 测试**

`tests/test_indexer.py`:
```python
"""Indexer 合并逻辑测试。"""

from code_memory.models import (
    AnnotationEntry,
    AnnotationLevel,
    AnnotationStore,
    BlockKind,
    ClassInfo,
    FileInfo,
    FunctionInfo,
    PackageInfo,
    ParameterInfo,
    Skeleton,
)


def _make_skeleton() -> Skeleton:
    """构建测试用 skeleton。"""
    func = FunctionInfo(
        name="greet", qualified_name="pkg.mod:greet",
        kind=BlockKind.FUNCTION, line_start=5, line_end=10,
        parameters=[ParameterInfo(name="name", annotation="str")],
        return_annotation="str",
        calls=["format"],
        signature_hash="sig_aaa", body_hash="body_bbb", call_hash="call_ccc",
    )
    file_info = FileInfo(
        file_path="pkg/mod.py", module_path="pkg.mod",
        functions=[func], line_count=20,
    )
    package = PackageInfo(
        package_path="pkg", module_path="pkg", files=["pkg/mod.py"],
    )
    return Skeleton(
        project_name="test", project_root="/tmp/test",
        source_dirs=["pkg"], scan_time="now",
        files=[file_info], packages=[package],
        call_graph={"pkg.mod:greet": ["format"]},
    )


def _make_annotations() -> AnnotationStore:
    """构建测试用 annotations。"""
    store = AnnotationStore(
        project_name="test", generation_time="now", model_used="test",
    )
    store.entries["pkg"] = AnnotationEntry(
        qualified_name="pkg",
        level=AnnotationLevel.MODULE,
        annotation={"what": "Main package", "exposes": ["greet"], "depends_on": [], "used_by": []},
    )
    store.entries["pkg.mod:greet"] = AnnotationEntry(
        qualified_name="pkg.mod:greet",
        level=AnnotationLevel.BLOCK,
        annotation={"what": "Say hello", "input": {"name": "person name"}, "output": "greeting string", "boundary": "none", "parent": "pkg"},
    )
    return store


def test_build_index_merges_block_entries():
    from code_memory.init.indexer import build_index
    skeleton = _make_skeleton()
    annotations = _make_annotations()

    index = build_index(skeleton, annotations)

    assert len(index.block_entries) == 1
    block = index.block_entries[0]
    assert block.id == "pkg.mod:greet"
    assert block.signature_hash == "sig_aaa"
    assert block.body_hash == "body_bbb"
    assert block.call_hash == "call_ccc"
    assert block.annotation is not None
    assert block.annotation["what"] == "Say hello"
    assert block.file_path == "pkg/mod.py"
    assert block.line_start == 5
    assert block.line_end == 10


def test_build_index_merges_module_entries():
    from code_memory.init.indexer import build_index
    skeleton = _make_skeleton()
    annotations = _make_annotations()

    index = build_index(skeleton, annotations)

    assert len(index.module_entries) == 1
    mod = index.module_entries[0]
    assert mod.id == "pkg"
    assert mod.annotation["what"] == "Main package"


def test_build_index_handles_missing_annotation():
    from code_memory.init.indexer import build_index
    skeleton = _make_skeleton()
    annotations = AnnotationStore(
        project_name="test", generation_time="now", model_used="test",
    )

    index = build_index(skeleton, annotations)

    assert len(index.block_entries) == 1
    assert index.block_entries[0].annotation is None
    assert index.block_entries[0].signature_hash == "sig_aaa"


def test_build_index_copies_call_graph():
    from code_memory.init.indexer import build_index
    skeleton = _make_skeleton()
    annotations = _make_annotations()

    index = build_index(skeleton, annotations)

    assert "pkg.mod:greet" in index.call_graph
    assert "format" in index.call_graph["pkg.mod:greet"]


def test_build_index_stats():
    from code_memory.init.indexer import build_index
    skeleton = _make_skeleton()
    annotations = _make_annotations()

    index = build_index(skeleton, annotations)

    assert index.stats["block_count"] == 1
    assert index.stats["module_count"] == 1
    assert index.stats["annotated"] >= 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/mac/Documents/projects/个人知识库 && python -m pytest tests/test_indexer.py -v`
Expected: FAIL — `code_memory.init.indexer` 不存在

- [ ] **Step 3: 实现 indexer.py**

创建 `code_memory/init/indexer.py`：

```python
"""
Step 3: 从 skeleton + annotations 合并构建索引。

纯确定性，不依赖 LLM，不读源码。
输入两个 JSON 文件，输出浅层索引。
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import (
    AnnotationLevel,
    AnnotationStore,
    IndexEntry,
    ShallowIndex,
    Skeleton,
)


def build_index(skeleton: Skeleton, annotations: AnnotationStore) -> ShallowIndex:
    """合并 skeleton 和 annotations，构建浅层索引。"""
    index = ShallowIndex(
        project_name=skeleton.project_name,
        extraction_time=datetime.now(timezone.utc).isoformat(),
    )

    # 处理包 → system/module 级
    for pkg in skeleton.packages:
        entry_data = annotations.entries.get(pkg.module_path)
        ann_dict = entry_data.annotation if entry_data else None
        level = entry_data.level if entry_data else AnnotationLevel.MODULE

        parent = pkg.module_path.rsplit(".", 1)[0] if "." in pkg.module_path else None

        idx_entry = IndexEntry(
            id=pkg.module_path,
            level=level,
            file_path=pkg.package_path + "/__init__.py",
            line_start=1,
            line_end=1,
            parent_module=parent,
            annotation=ann_dict,
        )

        if level == AnnotationLevel.SYSTEM:
            index.system_entries.append(idx_entry)
        else:
            index.module_entries.append(idx_entry)

    # 处理文件中的函数和类 → block 级
    for file_info in skeleton.files:
        parts = file_info.module_path.rsplit(".", 1)
        parent_module = parts[0] if len(parts) > 1 else file_info.module_path

        for func in file_info.functions:
            entry_data = annotations.entries.get(func.qualified_name)
            ann_dict = entry_data.annotation if entry_data else None

            index.block_entries.append(IndexEntry(
                id=func.qualified_name,
                level=AnnotationLevel.BLOCK,
                file_path=file_info.file_path,
                line_start=func.line_start,
                line_end=func.line_end,
                parent_module=parent_module,
                signature_hash=func.signature_hash,
                body_hash=func.body_hash,
                call_hash=func.call_hash,
                annotation=ann_dict,
                depends_on=func.calls,
            ))

        for cls in file_info.classes:
            cls_entry = annotations.entries.get(cls.qualified_name)
            cls_ann = cls_entry.annotation if cls_entry else None

            index.block_entries.append(IndexEntry(
                id=cls.qualified_name,
                level=AnnotationLevel.BLOCK,
                file_path=file_info.file_path,
                line_start=cls.line_start,
                line_end=cls.line_end,
                parent_module=parent_module,
                signature_hash=cls.signature_hash,
                body_hash=cls.body_hash,
                call_hash=cls.call_hash,
                annotation=cls_ann,
                depends_on=list(set(c for m in cls.methods for c in m.calls)),
            ))

            for method in cls.methods:
                m_entry = annotations.entries.get(method.qualified_name)
                m_ann = m_entry.annotation if m_entry else None

                index.block_entries.append(IndexEntry(
                    id=method.qualified_name,
                    level=AnnotationLevel.BLOCK,
                    file_path=file_info.file_path,
                    line_start=method.line_start,
                    line_end=method.line_end,
                    parent_module=parent_module,
                    signature_hash=method.signature_hash,
                    body_hash=method.body_hash,
                    call_hash=method.call_hash,
                    annotation=m_ann,
                    depends_on=method.calls,
                ))

    # 调用图直接搬运
    index.call_graph = skeleton.call_graph

    # 反向索引 used_by
    _populate_used_by(index)

    # 统计
    all_entries = index.system_entries + index.module_entries + index.block_entries
    index.stats = {
        "system_count": len(index.system_entries),
        "module_count": len(index.module_entries),
        "block_count": len(index.block_entries),
        "total": len(all_entries),
        "annotated": sum(1 for e in all_entries if e.annotation is not None),
    }

    return index


def _populate_used_by(index: ShallowIndex) -> None:
    """利用调用图填充 used_by 字段。"""
    id_to_entry: dict[str, IndexEntry] = {}
    for entries in (index.system_entries, index.module_entries, index.block_entries):
        for entry in entries:
            id_to_entry[entry.id] = entry

    for caller, callees in index.call_graph.items():
        for callee_name in callees:
            for eid, entry in id_to_entry.items():
                if eid.endswith(f":{callee_name}") or eid.endswith(f".{callee_name}"):
                    if caller not in entry.used_by:
                        entry.used_by.append(caller)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /Users/mac/Documents/projects/个人知识库 && python -m pytest tests/test_indexer.py -v`
Expected: ALL PASS

- [ ] **Step 5: 提交**

```bash
git add code_memory/init/indexer.py tests/test_indexer.py
git commit -m "feat(indexer): add skeleton+annotations merge to build shallow index"
```

---

### Task 6: 更新 CLI

**Files:**
- Modify: `code_memory/cli.py`

- [ ] **Step 1: 重写 cli.py**

完整替换 `code_memory/cli.py`：

```python
"""CLI 入口。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from .config import ProjectConfig


def main():
    parser = argparse.ArgumentParser(
        prog="code_memory",
        description="代码项目记忆系统 — 为代码项目构建外部挂载的记忆知识库",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    subparsers = parser.add_subparsers(dest="command")

    # init 子命令
    init_parser = subparsers.add_parser("init", help="初始化：全量注释生成 + 索引构建")
    init_parser.add_argument("project_path", type=Path, help="项目根目录路径")
    init_parser.add_argument("--config", type=Path, help="配置文件路径 (config.yaml)")
    init_parser.add_argument("--output", type=Path, help="记忆库输出目录（默认旁挂）")
    init_parser.add_argument(
        "--step", choices=["scan", "annotate", "index", "all"],
        default="all", help="只执行指定步骤",
    )
    init_parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 注释，只做静态分析")
    init_parser.add_argument("--dry-run", action="store_true", help="不建索引，只输出注释")

    # scan 子命令（便捷方式）
    scan_parser = subparsers.add_parser("scan", help="仅执行静态分析，输出骨架文件")
    scan_parser.add_argument("project_path", type=Path, help="项目根目录路径")
    scan_parser.add_argument("--config", type=Path, help="配置文件路径")
    scan_parser.add_argument("--output", type=Path, help="skeleton.json 输出路径")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.command == "scan":
        _run_scan(args)
    elif args.command == "init":
        _run_init(args)
    else:
        parser.print_help()
        sys.exit(1)


def _run_scan(args):
    """只运行静态分析。"""
    from .init.scanner import scan_project

    config = _load_config(args)
    logging.info(f"Scanning project: {config.project_root}")

    skeleton = scan_project(config)

    output_path = args.output or _default_memory_dir(args.project_path) / "skeleton.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(skeleton), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logging.info(f"Skeleton written to: {output_path}")
    logging.info(f"Stats: {skeleton.stats}")


def _run_init(args):
    """运行完整 init 流程或指定步骤。"""
    from .init.scanner import scan_project

    config = _load_config(args)
    memory_dir = args.output or _default_memory_dir(args.project_path)
    memory_dir.mkdir(parents=True, exist_ok=True)

    step = args.step

    # Step 1: 静态分析
    if step in ("scan", "all"):
        logging.info("Step 1: Static analysis...")
        skeleton = scan_project(config)
        skeleton_path = memory_dir / "skeleton.json"
        skeleton_path.write_text(
            json.dumps(asdict(skeleton), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logging.info(f"  Skeleton: {skeleton.stats}")
    else:
        skeleton_path = memory_dir / "skeleton.json"
        if not skeleton_path.exists():
            logging.error("skeleton.json not found. Run scan first.")
            sys.exit(1)
        skeleton = _load_skeleton(skeleton_path)

    if args.no_llm or step == "scan":
        logging.info("Done (--no-llm or --step scan)")
        return

    # Step 2: LLM 注释生成
    if step in ("annotate", "all"):
        logging.info("Step 2: LLM annotation generation...")
        from .init.annotator import generate_annotations

        # 加载已有注释（用于 overwrite_existing 检查）
        annotations_path = memory_dir / "annotations.json"
        existing = _load_annotations(annotations_path) if annotations_path.exists() else None

        annotations = generate_annotations(skeleton, config, existing=existing)
        annotations_path.write_text(
            json.dumps(_annotation_store_to_dict(annotations), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logging.info(f"  Annotations: {annotations.stats}")
    else:
        annotations_path = memory_dir / "annotations.json"
        if not annotations_path.exists():
            logging.error("annotations.json not found. Run annotate first.")
            sys.exit(1)
        annotations = _load_annotations(annotations_path)

    if args.dry_run or step == "annotate":
        logging.info("Done (--dry-run or --step annotate)")
        return

    # Step 3: 构建索引
    if step in ("index", "all"):
        logging.info("Step 3: Building index...")
        from .init.indexer import build_index

        index = build_index(skeleton, annotations)

        shallow_dir = memory_dir / "shallow"
        shallow_dir.mkdir(exist_ok=True)
        _write_index_files(index, shallow_dir)
        logging.info(f"  Index: {index.stats}")

    logging.info("Init complete.")


def _load_config(args) -> ProjectConfig:
    """加载配置。"""
    project_path = args.project_path.resolve()

    if hasattr(args, "config") and args.config:
        config = ProjectConfig.from_yaml(args.config)
        config.project_root = str(project_path)
    else:
        config = ProjectConfig.default_for_project(project_path)

    if config.source_dirs == ["src"]:
        for candidate in ["src", "lib", project_path.name]:
            if (project_path / candidate).is_dir():
                config.source_dirs = [candidate]
                break

    config.project_root = str(project_path)
    return config


def _default_memory_dir(project_path: Path) -> Path:
    """计算默认的旁挂记忆库目录。"""
    project_path = project_path.resolve()
    return project_path.parent / f".{project_path.name}-memory"


def _load_skeleton(path: Path):
    """从 JSON 加载 Skeleton。"""
    from .models import (
        Skeleton, FileInfo, PackageInfo, FunctionInfo, ClassInfo,
        ParameterInfo, BlockKind,
    )

    data = json.loads(path.read_text(encoding="utf-8"))

    files = []
    for fd in data.get("files", []):
        functions = []
        for fn in fd.get("functions", []):
            params = [ParameterInfo(**p) for p in fn.get("parameters", [])]
            functions.append(FunctionInfo(
                name=fn["name"], qualified_name=fn["qualified_name"],
                kind=BlockKind(fn["kind"]), line_start=fn["line_start"],
                line_end=fn["line_end"], parameters=params,
                return_annotation=fn.get("return_annotation"),
                docstring=fn.get("docstring"), decorators=fn.get("decorators", []),
                calls=fn.get("calls", []),
                signature_hash=fn.get("signature_hash", ""),
                body_hash=fn.get("body_hash", ""),
                call_hash=fn.get("call_hash", ""),
            ))

        classes = []
        for cd in fd.get("classes", []):
            methods = []
            for m in cd.get("methods", []):
                m_params = [ParameterInfo(**p) for p in m.get("parameters", [])]
                methods.append(FunctionInfo(
                    name=m["name"], qualified_name=m["qualified_name"],
                    kind=BlockKind(m["kind"]), line_start=m["line_start"],
                    line_end=m["line_end"], parameters=m_params,
                    return_annotation=m.get("return_annotation"),
                    docstring=m.get("docstring"), decorators=m.get("decorators", []),
                    calls=m.get("calls", []),
                    signature_hash=m.get("signature_hash", ""),
                    body_hash=m.get("body_hash", ""),
                    call_hash=m.get("call_hash", ""),
                ))
            classes.append(ClassInfo(
                name=cd["name"], qualified_name=cd["qualified_name"],
                line_start=cd["line_start"], line_end=cd["line_end"],
                docstring=cd.get("docstring"), bases=cd.get("bases", []),
                methods=methods, decorators=cd.get("decorators", []),
                signature_hash=cd.get("signature_hash", ""),
                body_hash=cd.get("body_hash", ""),
                call_hash=cd.get("call_hash", ""),
            ))

        files.append(FileInfo(
            file_path=fd["file_path"], module_path=fd["module_path"],
            docstring=fd.get("docstring"), imports=fd.get("imports", []),
            all_exports=fd.get("all_exports"), functions=functions,
            classes=classes, line_count=fd.get("line_count", 0),
        ))

    packages = [PackageInfo(**pd) for pd in data.get("packages", [])]

    return Skeleton(
        project_name=data["project_name"],
        project_root=data["project_root"],
        source_dirs=data["source_dirs"],
        scan_time=data["scan_time"],
        files=files, packages=packages,
        call_graph=data.get("call_graph", {}),
        stats=data.get("stats", {}),
    )


def _load_annotations(path: Path):
    """从 JSON 加载 AnnotationStore。"""
    from .models import AnnotationStore, AnnotationEntry, AnnotationLevel

    data = json.loads(path.read_text(encoding="utf-8"))
    entries = {}
    for qname, ed in data.get("entries", {}).items():
        entries[qname] = AnnotationEntry(
            qualified_name=qname,
            level=AnnotationLevel(ed["level"]),
            annotation=ed["annotation"],
        )
    return AnnotationStore(
        project_name=data["project_name"],
        generation_time=data["generation_time"],
        model_used=data["model_used"],
        entries=entries,
        skipped=data.get("skipped", []),
        stats=data.get("stats", {}),
    )


def _annotation_store_to_dict(store) -> dict:
    """将 AnnotationStore 序列化为可 JSON 化的 dict。"""
    return {
        "project_name": store.project_name,
        "generation_time": store.generation_time,
        "model_used": store.model_used,
        "entries": {
            qname: {
                "level": entry.level.value,
                "annotation": entry.annotation,
            }
            for qname, entry in store.entries.items()
        },
        "skipped": store.skipped,
        "stats": store.stats,
    }


def _write_index_files(index, shallow_dir: Path):
    """将索引写入文件。"""
    from dataclasses import asdict

    (shallow_dir / "system.json").write_text(
        json.dumps([asdict(e) for e in index.system_entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (shallow_dir / "modules.json").write_text(
        json.dumps([asdict(e) for e in index.module_entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (shallow_dir / "blocks.json").write_text(
        json.dumps([asdict(e) for e in index.block_entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (shallow_dir / "call_graph.json").write_text(
        json.dumps(index.call_graph, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

- [ ] **Step 2: 运行全量测试**

Run: `cd /Users/mac/Documents/projects/个人知识库 && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: 提交**

```bash
git add code_memory/cli.py
git commit -m "refactor(cli): remove write step, rename extract→index, use AnnotationStore"
```

---

### Task 7: 清理——删除 writer 和 extractor

**Files:**
- Delete: `code_memory/init/writer.py`
- Delete: `code_memory/init/extractor.py`

- [ ] **Step 1: 删除文件**

```bash
rm code_memory/init/writer.py
rm code_memory/init/extractor.py
```

- [ ] **Step 2: 确认没有残留引用**

```bash
cd /Users/mac/Documents/projects/个人知识库 && grep -r "writer" code_memory/ --include="*.py"
cd /Users/mac/Documents/projects/个人知识库 && grep -r "extractor" code_memory/ --include="*.py"
cd /Users/mac/Documents/projects/个人知识库 && grep -r "extract_index" code_memory/ --include="*.py"
cd /Users/mac/Documents/projects/个人知识库 && grep -r "write_annotations" code_memory/ --include="*.py"
```

Expected: 无匹配

- [ ] **Step 3: 运行全量测试确认无破坏**

Run: `cd /Users/mac/Documents/projects/个人知识库 && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: 提交**

```bash
git add -u code_memory/init/writer.py code_memory/init/extractor.py
git commit -m "cleanup: remove writer.py and extractor.py (replaced by non-invasive pipeline)"
```

---

### Task 8: 端到端验证

- [ ] **Step 1: 运行 scan 命令验证 hash 输出**

```bash
cd /Users/mac/Documents/projects/个人知识库 && python -m code_memory scan /Users/mac/Documents/projects/个人知识库/code_memory --output /tmp/test-memory/skeleton.json
```

Expected: skeleton.json 生成成功，函数条目包含非空的 signature_hash/body_hash/call_hash

- [ ] **Step 2: 检查 skeleton.json 中的 hash 字段**

```bash
python3 -c "
import json
data = json.load(open('/tmp/test-memory/skeleton.json'))
funcs = [f for fi in data['files'] for f in fi['functions']]
print(f'Total functions: {len(funcs)}')
hashed = [f for f in funcs if f.get('signature_hash')]
print(f'With hashes: {len(hashed)}')
if hashed:
    f = hashed[0]
    print(f'Example: {f[\"qualified_name\"]}')
    print(f'  sig:  {f[\"signature_hash\"]}')
    print(f'  body: {f[\"body_hash\"]}')
    print(f'  call: {f[\"call_hash\"]}')
"
```

Expected: 所有函数都有 16 字符 hex hash

- [ ] **Step 3: 验证 CLI help 反映新选项**

```bash
cd /Users/mac/Documents/projects/个人知识库 && python -m code_memory init --help
```

Expected: --step 选项显示 {scan,annotate,index,all}，不再有 write/extract

- [ ] **Step 4: 最终提交（如有修复）**

```bash
git add -A && git commit -m "test: end-to-end verification of non-invasive pipeline"
```

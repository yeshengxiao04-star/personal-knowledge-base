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

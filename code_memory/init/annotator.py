"""
Step 2: LLM 注释生成编排器。

读取 skeleton.json，从粗到细调用 LLM 生成三层注释。
产出注释修改清单 (AnnotationPlan)。
"""

from __future__ import annotations

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
    AnnotationPlan,
    FileInfo,
    FunctionInfo,
    ClassInfo,
    PackageInfo,
    Skeleton,
)

logger = logging.getLogger(__name__)


def generate_annotations(
    skeleton: Skeleton,
    config: ProjectConfig,
    llm_client: Optional[LLMClient] = None,
) -> AnnotationPlan:
    """生成完整的注释修改清单。从系统→模块→块逐层生成。"""
    if llm_client is None:
        llm_client = LLMClient(config.llm)

    plan = AnnotationPlan(
        project_name=skeleton.project_name,
        generation_time=datetime.now(timezone.utc).isoformat(),
        model_used=config.llm.model,
    )

    # Step 2.1: 生成系统级注释
    logger.info("Generating system-level annotation...")
    system_ann = _generate_system_annotation(skeleton, llm_client)
    if system_ann:
        plan.entries.append(system_ann)

    # Step 2.2: 生成模块级注释
    logger.info("Generating module-level annotations...")
    module_annotations: dict[str, str] = {}  # module_path → annotation content
    for pkg in skeleton.packages:
        ann_entry = _generate_module_annotation(
            pkg, skeleton, system_ann.content if system_ann else "", llm_client, config
        )
        if ann_entry:
            plan.entries.append(ann_entry)
            module_annotations[pkg.module_path] = ann_entry.content

    # Step 2.3: 生成块级注释
    logger.info("Generating block-level annotations...")
    for file_info in skeleton.files:
        _generate_block_annotations(
            file_info, skeleton, module_annotations, llm_client, config, plan
        )

    plan.stats = {
        "system_count": sum(1 for e in plan.entries if e.level == AnnotationLevel.SYSTEM),
        "module_count": sum(1 for e in plan.entries if e.level == AnnotationLevel.MODULE),
        "block_count": sum(1 for e in plan.entries if e.level == AnnotationLevel.BLOCK),
        "skipped_count": len(plan.skipped),
    }

    return plan


def _generate_system_annotation(
    skeleton: Skeleton, llm_client: LLMClient
) -> Optional[AnnotationEntry]:
    """生成系统级注释。"""
    packages_summary = _format_packages_summary(skeleton.packages)
    files_summary = _format_files_summary(skeleton.files[:50])  # 限制大小
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

    content = _clean_annotation(response.content)
    if not content:
        return None

    # 找到系统级注释应放置的文件（顶层 __init__.py）
    target_file = _find_system_init(skeleton)

    return AnnotationEntry(
        file_path=target_file,
        target_name="__module__",
        level=AnnotationLevel.SYSTEM,
        content=content,
        action="replace" if _has_existing_annotation(skeleton, target_file) else "insert",
    )


def _generate_module_annotation(
    pkg: PackageInfo,
    skeleton: Skeleton,
    system_context: str,
    llm_client: LLMClient,
    config: ProjectConfig,
) -> Optional[AnnotationEntry]:
    """为一个包生成模块级注释。"""
    # 如果已有注释且不覆盖，跳过
    if pkg.init_docstring and not config.annotation.overwrite_existing:
        if "@memory:module" in pkg.init_docstring:
            return None

    # 收集模块信息
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

    content = _clean_annotation(response.content)
    if not content:
        return None

    # __init__.py 的相对路径
    init_path = pkg.package_path + "/__init__.py"

    return AnnotationEntry(
        file_path=init_path,
        target_name="__module__",
        level=AnnotationLevel.MODULE,
        content=content,
        action="replace" if (pkg.init_docstring and "@memory:" in (pkg.init_docstring or "")) else "insert",
    )


def _generate_block_annotations(
    file_info: FileInfo,
    skeleton: Skeleton,
    module_annotations: dict[str, str],
    llm_client: LLMClient,
    config: ProjectConfig,
    plan: AnnotationPlan,
) -> None:
    """为文件中的函数和类生成块级注释。"""
    # 找到所属模块的注释作为上下文
    parts = file_info.module_path.rsplit(".", 1)
    parent_module = parts[0] if len(parts) > 1 else file_info.module_path
    module_context = module_annotations.get(parent_module, "")

    project_root = Path(skeleton.project_root)

    for func in file_info.functions:
        entry = _generate_single_block(
            func, file_info, module_context, project_root, llm_client, config
        )
        if entry:
            plan.entries.append(entry)
        elif func.qualified_name:
            plan.skipped.append(func.qualified_name)

    for cls in file_info.classes:
        # 为类本身生成注释
        cls_entry = _generate_class_block(
            cls, file_info, module_context, project_root, llm_client, config
        )
        if cls_entry:
            plan.entries.append(cls_entry)

        # 为类的方法生成注释
        for method in cls.methods:
            if method.name.startswith("_") and method.name != "__init__":
                plan.skipped.append(method.qualified_name)
                continue
            entry = _generate_single_block(
                method, file_info, module_context, project_root, llm_client, config
            )
            if entry:
                plan.entries.append(entry)
            else:
                plan.skipped.append(method.qualified_name)


def _generate_single_block(
    func: FunctionInfo,
    file_info: FileInfo,
    module_context: str,
    project_root: Path,
    llm_client: LLMClient,
    config: ProjectConfig,
) -> Optional[AnnotationEntry]:
    """为单个函数生成块级注释。"""
    # 跳过太短的函数
    func_lines = func.line_end - func.line_start + 1
    if func_lines < config.annotation.min_function_lines:
        return None

    # 跳过私有函数（_ 开头但非 __init__）
    if func.name.startswith("_") and func.name != "__init__":
        return None

    # 已有 @memory 注释且不覆盖
    if func.docstring and "@memory:block" in func.docstring and not config.annotation.overwrite_existing:
        return None

    # 读取函数源码
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

    content = _clean_annotation(response.content)
    if not content:
        return None

    return AnnotationEntry(
        file_path=file_info.file_path,
        target_name=func.qualified_name,
        level=AnnotationLevel.BLOCK,
        content=content,
        action="replace" if (func.docstring and "@memory:" in (func.docstring or "")) else "insert",
        line_hint=func.line_start,
    )


def _generate_class_block(
    cls: ClassInfo,
    file_info: FileInfo,
    module_context: str,
    project_root: Path,
    llm_client: LLMClient,
    config: ProjectConfig,
) -> Optional[AnnotationEntry]:
    """为类生成块级注释。"""
    if cls.docstring and "@memory:block" in cls.docstring and not config.annotation.overwrite_existing:
        return None

    source_code = _read_source_range(project_root / file_info.file_path, cls.line_start, min(cls.line_start + 30, cls.line_end))
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

    content = _clean_annotation(response.content)
    if not content:
        return None

    return AnnotationEntry(
        file_path=file_info.file_path,
        target_name=cls.qualified_name,
        level=AnnotationLevel.BLOCK,
        content=content,
        action="replace" if (cls.docstring and "@memory:" in (cls.docstring or "")) else "insert",
        line_hint=cls.line_start,
    )


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────


def _clean_annotation(raw: str) -> str:
    """清理 LLM 输出，提取纯注释内容。"""
    # 去掉可能的 markdown code block 包裹
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    # 确保以 @memory: 开头
    if not raw.startswith("@memory:"):
        # 尝试找到 @memory: 行
        for i, line in enumerate(raw.split("\n")):
            if line.strip().startswith("@memory:"):
                raw = "\n".join(raw.split("\n")[i:])
                break
        else:
            return ""

    return raw.strip()


def _find_system_init(skeleton: Skeleton) -> str:
    """找到系统级注释应放的文件。"""
    # 优先找顶层 __init__.py
    for pkg in skeleton.packages:
        if "/" not in pkg.package_path or pkg.package_path.count("/") == 1:
            return pkg.package_path + "/__init__.py"
    # fallback: 第一个文件
    if skeleton.files:
        return skeleton.files[0].file_path
    return "__init__.py"


def _has_existing_annotation(skeleton: Skeleton, file_path: str) -> bool:
    """检查文件是否已有 @memory 注释。"""
    for f in skeleton.files:
        if f.file_path == file_path and f.docstring and "@memory:" in f.docstring:
            return True
    return False


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
    # 统计每个模块被哪些其他模块导入
    module_paths = {f.module_path for f in skeleton.files}
    import_map: dict[str, set[str]] = {}

    for f in skeleton.files:
        for imp in f.imports:
            # 只保留项目内部的导入
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
    # 收集所有公开函数
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
    internal = [i for i in sorted(imports) if not i.startswith(("os", "sys", "pathlib", "typing", "dataclass", "enum", "json", "re", "ast", "datetime", "collections", "abc", "functools", "logging"))]
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

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

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

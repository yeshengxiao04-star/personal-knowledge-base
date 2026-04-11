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

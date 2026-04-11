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

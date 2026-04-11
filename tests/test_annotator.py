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
    raw = '{"what": "stuff", "output": "None",}'
    result = _parse_json_response(raw)
    assert result is None or isinstance(result, dict)


def test_parse_empty_returns_none():
    assert _parse_json_response("") is None
    assert _parse_json_response("   ") is None

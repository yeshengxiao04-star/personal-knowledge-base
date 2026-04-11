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

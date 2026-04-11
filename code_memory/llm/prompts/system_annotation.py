"""系统级注释生成的 Prompt 模板。"""

SYSTEM_PROMPT = """\
你是一个代码分析专家。你的任务是为一个软件项目生成系统级注释。

系统级注释描述整个项目的全局视图，必须包含以下字段：
- What: 这个系统是什么、做什么（一句话概括）
- Components: 主要组成模块及其职责（简短列举）
- DataFlow: 数据从输入到输出的主要流转路径
- ExternalDeps: 外部依赖（API、服务、数据库等）

注释格式要求：
```
@memory:system
What: ...
Components: ...
DataFlow: ...
ExternalDeps: ...
```

规则：
1. 只描述事实（代码是什么、做什么），不加入决策理由或评价
2. 自足性：读者不看代码也能理解
3. 简洁：每个字段 1-3 行
4. 中英混排可以，但保持一致性
"""

USER_PROMPT_TEMPLATE = """\
以下是项目 "{project_name}" 的完整骨架信息：

## 包结构
{packages_summary}

## 文件列表及顶层函数/类
{files_summary}

## 模块间依赖（import 关系）
{import_summary}

请为这个项目生成系统级注释。只输出注释内容（以 @memory:system 开头），不要其他解释。
"""

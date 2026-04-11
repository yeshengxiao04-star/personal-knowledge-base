# 代码项目记忆系统 — Init 管线设计

## Context

`代码项目记忆系统方案.md` 核心洞察："代码不是记忆的对象，注释才是"。本系统为代码项目构建外部挂载的记忆知识库，帮助 AI 快速理解项目并辅助开发。

**信息源定位**：事实视角（代码是什么、做什么、怎么关联的）。与项目文件（目标视角）完全独立，两者的交叉验证在更高层发生，不在本系统内。

**实施路径**：Init-first。先把注释生成管线做对，再扩展 Maintain 和 Use 阶段。

**试验田**：Vibe_Workflow_Studio（105 个 Python 源文件、175K LOC、注释质量已较好）。

---

## 系统总览

```
三个阶段：
  Init    — 全量注释生成 + 索引构建（一次性，可重跑）
  Maintain — git diff 驱动的增量更新（后期）
  Use     — 概览加载 + 语义查询（后期）

物理布局：
  /projects/Vibe_Workflow_Studio/          ← 原项目（注释写在这里）
  /projects/.Vibe_Workflow_Studio-memory/  ← 旁挂记忆库（索引在这里）
```

注释住在代码里（编码层），索引住在外部（检索层）。

---

## 核心设计原则

### 记忆基本元素（注释）的四维结构

每条注释携带四个信息维度：
1. **自足性** — 脱离上下文可理解
2. **事实核心** — 这段代码是什么、做什么
3. **关联指向** — 和什么有关
4. **约束边界** — 不做什么、什么条件下失效

**不在注释里放的**：决策理由（是推断不是事实，无法从代码生成，应记录在迭代历史和项目文档中）。

### 六条注释原则

1. **覆盖优先于深度** — 每个模块和公开函数都有注释，但不追求深入分析
2. **三层最小信息要求** — 系统级（做什么+组成+数据流）、模块级（做什么+接口+依赖）、块级（做什么+输入输出）
3. **向上锚定** — 块级注释包含父模块路径引用
4. **调用图双链** — 被 3 处以上引用的公共函数/类，标注主要调用方
5. **格式可机器提取** — 固定结构化格式，正则可确定性提取
6. **为深层重注释预留空间** — 支持后续追加分析视角字段

### 信息卫生

- Init/Maintain 只读代码，不读项目文件（CLAUDE.md、设计文档等）
- 外部索引只存从代码注释中提取的信息
- 记忆库与项目文件各自保持纯净

---

## Init 管线：三步走

### Step 1：静态分析（确定性，不用 LLM）

扫描项目 Python 文件，用 AST 提取：
- 文件列表、目录结构、模块层级关系
- 已有的 docstring 和注释（现状）
- 函数/类的签名、参数类型、返回类型
- 调用图（`import` + 函数调用的静态分析）
- `__all__` 导出表

**产出**：`skeleton.json`（项目骨架，纯结构信息）

### Step 2：LLM 注释生成（可配置模型）

从粗到细，逐层注入上下文：
1. 系统级注释（输入：全局骨架）
2. 模块级注释（输入：系统级产出 + 该模块骨架）
3. 块级注释（输入：模块级产出 + 该函数/类代码）

规则：
- 已有高质量 docstring → 保留，只补充缺失维度
- LLM 模型通过配置文件指定（默认用快速模型如 kimi-k2）
- 少于 N 行的简单函数可跳过

**产出**：注释修改清单（文件 + 位置 + 注释内容）

### Step 3：写回 + 提取

- 按清单将注释写回源文件
- 从注释化代码中确定性提取结构化数据到浅层索引
- 提取用正则 + AST，不用 LLM

**产出**：代码文件被注释化 + 浅层索引建成

```
代码文件 ──AST──→ 项目骨架 ──LLM──→ 注释清单 ──写回──→ 注释化代码
                                                    │
                                              确定性提取
                                                    │
                                                    ↓
                                               浅层索引
```

---

## 注释格式

三层注释均使用 `@memory:` 前缀标记，正则一扫分类。

**系统级**（`src/__init__.py`）：
```python
"""
@memory:system
What: 端到端编译工具链，将自然语言转换为 Dify 可导入的 DSL 文件
Components: stage0(对话), stage1(综合), stage_a(架构规划),
            stage2(WDS→IR), stage3(IR→DSL), repair(修复)
DataFlow: NaturalLanguage → Blueprint → DesignSpec → WDS → IR → DifyDSL
ExternalDeps: Dify Console API, LLM API (OpenAI/Anthropic/Kimi)
"""
```

**模块级**（各包 `__init__.py`）：
```python
"""
@memory:module
What: WDS → IR 转换，解析 YAML 并构建平台无关的中间表示
Exposes: compile_wds_to_ir()
DependsOn: models.wds, models.ir
UsedBy: stage3, repair
"""
```

**块级**（函数/类 docstring）：
```python
def compute_layout(ir: WorkflowIR) -> dict[str, tuple[float, float]]:
    """
    @memory:block
    What: 计算每个节点的 (x, y) 画布坐标，使用拓扑 BFS 分层
    Input: WorkflowIR (已验证的完整图结构)
    Output: dict[node_id, (x, y)]
    Boundary: 假设 IR 已通过验证，不处理孤立节点
    Parent: src.stage3
    """
```

字段名固定：What / Components / DataFlow / ExternalDeps / Exposes / DependsOn / UsedBy / Input / Output / Boundary / Parent

---

## 索引设计

### 定位策略：双重标识

- **主键**：稳定标识符（qualified name），如 `src.stage2.wds_parser:parse_wds_yaml`
- **辅键**：行号范围，每次 maintain 刷新

主键在代码结构不变时永远稳定。git diff 改了上面的代码，行号漂移，但主键不变。Maintain 阶段对变化文件重新 AST 解析刷新行号。

### 索引条目结构

```json
{
  "id": "src.stage2.wds_parser:parse_wds_yaml",
  "level": "block",
  "annotation": "@memory:block\nWhat: 解析 WDS YAML...\n...",
  "file_path": "vibe-workflow/src/stage2/wds_parser.py",
  "line_start": 42,
  "line_end": 89,
  "parent_module": "src.stage2",
  "used_by": ["src.stage3.dify_mapper", "src.repair.llm_repair"],
  "depends_on": ["src.models.wds"]
}
```

### 旁挂目录结构

```
.Vibe_Workflow_Studio-memory/
├── config.yaml                 # 项目元数据、LLM 模型配置、排除规则
├── skeleton.json               # Step 1 产出（AST 骨架）
├── shallow/
│   ├── system.json             # 系统级注释索引
│   ├── modules.json            # 全部模块级注释索引
│   ├── blocks.json             # 全部块级注释索引
│   └── call_graph.json         # 调用图（静态分析产出）
├── vectors/                    # 后期：向量库
├── tags/                       # 后期：标签索引
└── history/
    ├── init_log.json           # 首次初始化记录
    └── updates/                # maintain 增量记录
```

### 配置文件 config.yaml

```yaml
project_name: Vibe_Workflow_Studio
project_root: ../Vibe_Workflow_Studio
source_dirs: [vibe-workflow/src]
exclude_patterns: [__pycache__, .git, .venv, dev/tests, dev/fixtures]
llm:
  model: kimi-k2
  api_base: null
  temperature: 0.3
annotation:
  overwrite_existing: false
  min_function_lines: 3
```

---

## 项目结构（代码）

```
个人知识库/code_memory/
├── __init__.py
├── __main__.py                  # python -m code_memory init ...
├── cli.py                       # argparse: init / update / overview / search
├── config.py                    # 加载 config.yaml
├── models.py                    # 数据模型（Skeleton, AnnotationPlan, IndexEntry）
├── init/
│   ├── __init__.py
│   ├── scanner.py               # Step 1: AST 静态分析 → skeleton.json
│   ├── annotator.py             # Step 2: LLM 注释生成 → 注释清单
│   ├── writer.py                # Step 3a: 写回注释到源文件
│   └── extractor.py             # Step 3b: 从注释提取到索引
├── maintain/                    # 后期
│   ├── __init__.py
│   ├── diff_detector.py         # git diff → 变化文件列表
│   └── incremental_updater.py   # 增量重注释 + 索引刷新
├── use/                         # 后期
│   ├── __init__.py
│   ├── overview.py              # 概览模式
│   └── search.py                # 查询模式
└── llm/
    ├── __init__.py
    ├── client.py                # LLM 调用抽象层（支持多模型）
    └── prompts/
        ├── system_annotation.py
        ├── module_annotation.py
        └── block_annotation.py
```

---

## 实施步骤

### Step 1: models.py
数据模型。用 dataclass 或 Pydantic。定义 Skeleton、ModuleInfo、FunctionInfo、AnnotationEntry、IndexEntry。

### Step 2: init/scanner.py
AST 静态分析。核心逻辑：
- `pathlib.rglob("*.py")`，跳过排除模式
- `ast.parse()` 提取模块结构、docstring、`__all__`、函数签名
- 静态分析 import 和函数调用，构建调用图
- 输出 `skeleton.json`

### Step 3: llm/client.py + prompts/
LLM 调用层。支持配置不同模型。Prompt 模板分系统/模块/块三级。

### Step 4: init/annotator.py
注释生成的编排逻辑：
- 读取 skeleton.json
- 按三层顺序调用 LLM（系统→模块→块）
- 每层产出注入下一层作为上下文
- 对已有高质量注释做差异判断（保留/补充/跳过）
- 输出注释修改清单

### Step 5: init/writer.py
将注释写回源文件。关键：
- 精确插入/替换 docstring 位置
- 保持代码缩进和格式
- 不改动非注释部分

### Step 6: init/extractor.py
从注释化代码中提取索引：
- 正则匹配 `@memory:system|module|block` 
- 解析固定字段（What / Exposes / DependsOn 等）
- 生成 qualified name 作为主键
- 关联调用图信息
- 输出 shallow/ 目录下的 JSON 索引文件

### Step 7: cli.py
```bash
python -m code_memory init /path/to/project [--config config.yaml]
python -m code_memory update /path/to/project     # 后期
python -m code_memory overview /path/to/project   # 后期
python -m code_memory search "query" /path/to/project  # 后期
```

---

## 验证策略

1. **Step 1 验证**：对 VWS 跑 scanner，检查 skeleton.json 是否完整覆盖 105 个源文件、正确提取模块结构和调用关系

2. **Step 2 验证**：抽检 LLM 生成的注释质量
   - 取 5 个已有高质量文档的模块，对比生成注释 vs 手工文档
   - 检查四维信息是否完整（事实、关联、边界、自足）
   - 检查是否误入决策信息

3. **Step 3 验证**：写回后项目测试仍全部通过（注释不改行为）

4. **索引验证**：从索引中随机取 10 个条目，按主键定位到源文件验证准确性

---

## 依赖

- Python 3.10+（stdlib: ast, pathlib, dataclasses, argparse, json, re）
- LLM SDK（anthropic / openai，按配置的模型确定）
- 无其他外部依赖

---

## 关键文件路径

| 新建文件 | 作用 |
|----------|------|
| `code_memory/models.py` | 数据模型，全局依赖 |
| `code_memory/init/scanner.py` | AST 静态分析，最大确定性组件 |
| `code_memory/init/annotator.py` | LLM 注释生成编排，核心智能 |
| `code_memory/init/writer.py` | 写回源文件，精度要求高 |
| `code_memory/init/extractor.py` | 确定性提取，索引质量保证 |
| `code_memory/llm/client.py` | LLM 调用抽象层 |

| 参考文件（只读） | 用途 |
|------------------|------|
| `Vibe_Workflow_Studio/vibe-workflow/src/` | init 的输入，试验田 |
| `Vibe_Workflow_Studio/CLAUDE.md` | 了解项目全貌（不作为 init 输入） |

---

## 后期扩展（当前不实施）

- **Maintain**：git diff → 增量重注释 → 刷新行号 → 更新索引 → 记录 history
- **Use**：概览模式（加载系统级+模块级摘要）+ 查询模式（语义检索注释）
- **深层重注释**：从稳定性/安全性/性能等质心视角对代码追加分析标注
- **向量化**：注释 embedding → 向量检索
- **验证闭环**：在本系统（事实视角）与项目文件（目标视角）之上的对照层

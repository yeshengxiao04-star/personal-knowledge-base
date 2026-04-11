# 代码项目记忆系统

为代码项目构建外部挂载的记忆知识库，帮助 AI 快速理解项目并辅助开发。

源自「代码项目记忆系统方案.md」的概念设计，当前在 `code_memory/` 包中实施。试验田：Vibe_Workflow_Studio。

## 定位与信息卫生

- **信息源定位**：事实视角（代码是什么、做什么、怎么关联的）
- **独立于**：项目文件（CLAUDE.md / 设计文档 = 目标视角）
- **信息卫生原则**：两个信息源各自保持纯净，不互相污染。Init/Maintain 只读代码不读项目文件，外部索引只存从代码注释中提取的信息。交叉验证在两个系统之上的更高层发生，不在本系统内。

## 核心洞察

代码本身不是记忆的对象，注释才是。代码是原始感觉输入，注释是对代码的语义编码。LLM 不需要"记住"代码怎么写，只需要记住代码"是什么、为什么、和什么有关"。

## 记忆基本元素（注释）的四维结构

每条注释携带四个信息维度：
1. **自足性** — 脱离上下文代码可理解
2. **事实核心** — 这段代码是什么、做什么
3. **关联指向** — 和什么有关
4. **约束边界** — 不做什么、什么条件下失效

**不在注释里放的**：决策理由。决策是推断不是事实，无法仅从代码生成，且容易过时被推翻。决策历史应记录在迭代记录和项目文档中。

## 六条注释原则

1. **覆盖优先于深度** — 每个模块和公开函数都有注释，不追求个别深入
2. **三层最小信息要求** — 系统级（做什么+组成+数据流）、模块级（做什么+接口+依赖）、块级（做什么+输入输出）
3. **向上锚定** — 块级注释包含父模块路径引用
4. **调用图双链** — 被 3 处以上引用的公共函数/类，标注主要调用方
5. **格式可机器提取** — 固定 `@memory:system|module|block` 前缀 + 固定字段名，正则确定性提取
6. **为深层重注释预留空间** — 后续可从稳定性/安全性/性能等质心视角追加字段

## 架构：三阶段 + 旁挂存储

```
三个阶段：
  Init    — 全量注释生成 + 索引构建（一次性，可重跑）
  Maintain — git diff 驱动的增量更新（后期）
  Use     — 概览加载 + 语义查询（后期）

物理布局：
  /projects/<ProjectName>/             ← 原项目（注释写在这里）
  /projects/.<ProjectName>-memory/     ← 旁挂记忆库（索引在这里）
```

注释住在代码里（编码层），索引住在外部（检索层）。

## Init 管线：三步走

1. **静态分析**（确定性）— AST 扫描 → `skeleton.json`（项目骨架）
2. **LLM 注释生成**（可配置模型）— 系统→模块→块逐层注入上下文 → 注释修改清单
3. **写回 + 提取** — 注释写回源文件 + 确定性提取到浅层索引

## 索引设计：双重标识

- **主键**：qualified name（如 `src.stage2.wds_parser:parse_wds_yaml`），代码结构不变则永远稳定
- **辅键**：行号范围，每次 maintain 刷新

索引存注释 + 代码指针。查询时返回注释（已加工的认知），需要时再按指针读代码（原始输入）。

## 旁挂目录结构

```
.<ProjectName>-memory/
├── config.yaml              # 项目元数据、LLM 模型配置、排除规则
├── skeleton.json            # Step 1 产出
├── shallow/                 # 浅层索引
│   ├── system.json
│   ├── modules.json
│   ├── blocks.json
│   └── call_graph.json
├── vectors/                 # 后期：向量库
├── tags/                    # 后期：标签索引
└── history/                 # 版本沿革
```

## CLI

```bash
python -m code_memory scan <project_path> --config config.yaml    # 仅静态分析
python -m code_memory init <project_path> --config config.yaml    # 完整 Init
python -m code_memory init <project_path> --no-llm                # 只跑 Step 1
python -m code_memory init <project_path> --dry-run               # 不写回文件
python -m code_memory init <project_path> --step annotate         # 只跑指定步骤
```

## 当前状态

| 组件 | 状态 |
|------|------|
| Step 1 scanner | ✅ 已实现，对 VWS 验证通过（105 文件、332 函数、469 调用图） |
| Step 2 annotator + prompts | ✅ 已实现，待 LLM API 实际调用验证 |
| Step 3a writer | ✅ 已实现，待验证 |
| Step 3b extractor | ✅ 已实现，待验证 |
| CLI | ✅ 已实现 |
| Maintain（增量更新） | 🔲 后期 |
| Use（概览+查询） | 🔲 后期 |
| 深层质心重注释 | 🔲 后期 |

## 试验田

Vibe_Workflow_Studio（105 Python 源文件、20K LOC、77% 已有 docstring 覆盖率）

## 项目内文件索引

| 文件 | 说明 |
|------|------|
| `code_memory/` | 代码记忆系统实现 |
| `docs/code-memory-init-design.md` | Init 管线完整设计文档 |
| `代码项目记忆系统方案.md` | 原始概念方案 |
| `文档知识库方案.md` | 文档知识库方案（Obsidian + XYZ 标签体系） |
| `知识库结构化整理方案.md` | 双层涌现标签体系设计 |
| `vault分析报告.md` | TF-IDF 聚类分析结果 |
| `群友知识库体系_工程复现参考.md` | 原系统逆向分析 |

## 关联项目

- **AI 记忆工程**：记忆系统的分层涌现模型（本项目为其提供工程验证）
- **Vibe_Workflow_Studio**：首个试验田项目

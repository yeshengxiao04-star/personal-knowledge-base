# 个人知识库 — 项目文档

## 项目定位

三维标签驱动的个人知识 RAG 系统。双重身份：
1. **独立产品**：基于 Obsidian + Python 的个人知识管理与检索系统
2. **实验田**：为 AI 记忆涌现模型提供 ground truth，验证 HDBSCAN 能否自动复现人工标签分类

源自对群友个人知识库系统（2342 条笔记、Python 全栈自建）的截图逆向分析。

## 架构

```
Obsidian层（零代码，日常使用）
  · Templater — 交互式笔记模板（五段式 + XYZ标签弹窗选择）
  · Dataview — 标签统计仪表盘、切面查询
  · Graph View — 知识图谱浏览
  · obsidian-git — 版本控制
─────────────────────────────
Python层（检索与生成，Phase 2+ 开始）
  · python-frontmatter — 解析 .md + YAML
  · Embedding → 向量存储 → 标签预筛选 → 向量召回 → Rerank → LLM
  · Thread Dossier Builder（Phase 5）
─────────────────────────────
两层通过文件系统共享 vault 目录，无同步机制
```

## XYZ 三轴标签体系

- **X轴（主题领域）**：AI/Memory · AI/Collaboration · AI/Engineering · AI/Industry · Cognition · Career · Writing
- **Y轴（认知功能）**：Architecture · Decision · Mechanism · Model · Optimization · Protocol · Reference · Troubleshooting
- **Z轴（拓扑角色）**：Boundary · Node · Matrix · Pipeline

标签格式：`x/AI/Memory`、`y/Mechanism`、`z/Node`，写在 YAML frontmatter 的 tags 字段中。Obsidian 原生支持层级标签展开。

## 关键路径与文件

| 路径 | 说明 |
|------|------|
| `/Users/mac/Documents/JXD&AI/` | 实际 Obsidian vault（118 篇笔记） |
| `群友知识库体系_工程复现参考.md` | 原系统逆向分析（截图级别） |
| `知识库结构化整理方案.md` | 双层涌现标签体系设计 + Pipeline 规划 |
| `vault分析报告.md` | TF-IDF 聚类分析结果（107 篇、10 个簇） |
| `代码项目记忆系统方案.md` | 衍生概念：将记忆体系迁移到代码项目管理 |

## 实施阶段

| Phase | 内容 | 状态 |
|-------|------|------|
| 1 | Obsidian vault 结构化改造（标签表、模板、仪表盘、测试笔记） | ✅ 完成 |
| 2a | Vault TF-IDF 分析 → 涌现标签候选池 + 聚类报告 | ✅ 完成 |
| 2b | Pipeline 工程化（Python 脚本：扫描→分析→写回 frontmatter） | 🔲 待开始 |
| 2c | 批量改造（存量笔记补 frontmatter + 标签 + 双链） | 🔲 待开始 |
| 3 | Rerank + LLM 生成管线 | 🔲 待开始 |
| 4 | 知识图谱可视化增强 | 🔲 待开始 |
| 5 | Thread Dossier Builder | 🔲 待开始 |

## 核心设计决策

### 双层涌现标签（知识库结构化整理方案）

在 XYZ 三轴之上新增两个维度：
- **`emergent_tags`**（第四维）：TF-IDF + HDBSCAN 无监督聚类，数据驱动的语义标签
- **`anchor_tags`**（第五维）：预定义质心概念 + Embedding 距离，认知框架牵引标签

质心概念池（目前仅一个）：`不隔`（王国维《人间词话》，审美偏好锚点）

### 存量笔记处理原则

- Frontmatter 是纯索引层，不动原文内容
- 双链增量插入，不破坏原有结构
- 五段式模板只用于新笔记，不强行套用存量

### TF-IDF 分析关键发现

- 107 篇笔记聚为 10 个簇，与 X 轴标签体系大体吻合
- `x/AI/Collaboration` 与 `x/Cognition` 在语义上高度耦合（协作校准文档含大量认知特质描述）
- `x/Writing` 内部可能需要子标签（Poetry / Essay / Literary-Criticism）
- 标签覆盖率约 20%，大量存量笔记尚未标注

## 技术栈

| 层 | 组件 | 选型 |
|----|------|------|
| Obsidian | 模板 | Templater |
| Obsidian | 查询 | Dataview |
| Python | 文件解析 | python-frontmatter |
| Python | Embedding | 待定（text-embedding-3 / BGE / GTE） |
| Python | 向量存储 | 待定（Chroma / Qdrant / FAISS） |
| Python | Rerank | 初期余弦排序，后期 cross-encoder |
| Python | LLM | Claude API |

## 代码项目记忆系统 (`code_memory/`)

将个人知识库的记忆体系迁移到代码工程领域。为代码项目构建外部挂载的记忆知识库。

### 定位与信息卫生

- **信息源定位**：事实视角（代码是什么、做什么、怎么关联的）
- **独立于**：项目文件（CLAUDE.md / 设计文档 = 目标视角）
- **信息卫生原则**：两个信息源各自保持纯净，不互相污染。Init/Maintain 只读代码不读项目文件，外部索引只存从代码注释中提取的信息。交叉验证在两个系统之上的更高层发生，不在本系统内。

### 核心洞察

代码本身不是记忆的对象，注释才是。代码是原始感觉输入，注释是对代码的语义编码。LLM 不需要"记住"代码怎么写，只需要记住代码"是什么、为什么、和什么有关"。

### 记忆基本元素（注释）的四维结构

每条注释携带四个信息维度：
1. **自足性** — 脱离上下文代码可理解
2. **事实核心** — 这段代码是什么、做什么
3. **关联指向** — 和什么有关
4. **约束边界** — 不做什么、什么条件下失效

**不在注释里放的**：决策理由。决策是推断不是事实，无法仅从代码生成，且容易过时被推翻。决策历史应记录在迭代记录和项目文档中。

### 六条注释原则

1. **覆盖优先于深度** — 每个模块和公开函数都有注释，不追求个别深入
2. **三层最小信息要求** — 系统级（做什么+组成+数据流）、模块级（做什么+接口+依赖）、块级（做什么+输入输出）
3. **向上锚定** — 块级注释包含父模块路径引用
4. **调用图双链** — 被 3 处以上引用的公共函数/类，标注主要调用方
5. **格式可机器提取** — 固定 `@memory:system|module|block` 前缀 + 固定字段名，正则确定性提取
6. **为深层重注释预留空间** — 后续可从稳定性/安全性/性能等质心视角追加字段

### 架构：三阶段 + 旁挂存储

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

### Init 管线：三步走

1. **静态分析**（确定性）— AST 扫描 → `skeleton.json`（项目骨架）
2. **LLM 注释生成**（可配置模型）— 系统→模块→块逐层注入上下文 → 注释修改清单
3. **写回 + 提取** — 注释写回源文件 + 确定性提取到浅层索引

### 索引设计：双重标识

- **主键**：qualified name（如 `src.stage2.wds_parser:parse_wds_yaml`），代码结构不变则永远稳定
- **辅键**：行号范围，每次 maintain 刷新

索引存注释 + 代码指针。查询时返回注释（已加工的认知），需要时再按指针读代码（原始输入）。

### 旁挂目录结构

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

### CLI

```bash
python -m code_memory scan <project_path> --config config.yaml    # 仅静态分析
python -m code_memory init <project_path> --config config.yaml    # 完整 Init
python -m code_memory init <project_path> --no-llm                # 只跑 Step 1
python -m code_memory init <project_path> --dry-run               # 不写回文件
python -m code_memory init <project_path> --step annotate         # 只跑指定步骤
```

### 当前状态

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

### 试验田

Vibe_Workflow_Studio（105 Python 源文件、20K LOC、77% 已有 docstring 覆盖率）

## 关联项目

- **AI 记忆工程**：记忆系统的分层涌现模型（本项目为其提供人工标签 ground truth）
- **代码项目记忆系统**：`code_memory/` 包，已在本项目中实施

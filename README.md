# 三维标签驱动的个人知识 RAG 系统

基于群友个人知识库系统的逆向分析与工程复现。同时作为 AI 记忆工程的衍生实验项目，为记忆涌现模型提供工程验证数据。

## 项目定位

- **独立项目**：可日常使用的个人知识管理系统
- **实验田**：为 AI 记忆工程提供人工标签 ground truth，验证涌现聚类（HDBSCAN）能否自动复现人工分类

## 架构

```
┌─────────────────────────────────────────┐
│  Obsidian层（零代码，日常使用）            │
│  · 笔记撰写与五段式模板（Templater）       │
│  · XYZ三轴标签管理（YAML frontmatter）    │
│  · 标签统计与切面查询（Dataview）          │
│  · 知识图谱浏览（原生 Graph View）         │
├─────────────────────────────────────────┤
│  Python层（检索与生成）                   │
│  · Markdown + YAML 解析                  │
│  · Embedding + 向量存储                  │
│  · 标签预筛选 → 向量召回 → Rerank → LLM  │
│  · Thread Dossier Builder（后期）        │
└─────────────────────────────────────────┘
        ↕ 共享 Obsidian vault 文件目录
```

## XYZ 三轴标签体系

**X轴 · 主题领域：** AI/Memory · AI/Collaboration · AI/Engineering · AI/Industry · Cognition · Career · Writing

**Y轴 · 认知功能：** Architecture · Decision · Mechanism · Model · Optimization · Protocol · Reference · Troubleshooting

**Z轴 · 拓扑角色：** Boundary · Node · Matrix · Pipeline

## 实施阶段

| Phase | 内容 | 状态 |
|-------|------|------|
| **Phase 1** | Obsidian vault 结构化改造 | ✅ 完成 |
| **Phase 2** | Python 读取 vault + Embedding | 🔲 待开始 |
| **Phase 3** | Rerank + LLM 生成管线 | 🔲 待开始 |
| **Phase 4** | 知识图谱可视化增强 | 🔲 待开始 |
| **Phase 5** | Thread Dossier Builder | 🔲 待开始 |

### Phase 1 完成内容

**Obsidian vault：** `/Users/mac/Documents/JXD&AI/`（已有 vault，叠加结构化改造）

- [x] 三轴标签分类表（`00-系统/标签分类表.md`）
- [x] Templater 交互式笔记模板（弹窗选 X/Y/Z 标签 + 五段式正文）
- [x] Dataview 统计仪表盘（三轴分组计数 + 最近更新）
- [x] Templater 插件配置（模板目录指向 `00-系统/模板/`）
- [x] 5 条测试笔记标注 frontmatter

### Phase 1 待验证

- [ ] Dataview 表格正确渲染
- [ ] Templater 新建笔记弹窗正常
- [ ] 标签面板 x/y/z/ 层级树正确展开

## 技术栈

| 层 | 组件 | 选型 |
|----|------|------|
| Obsidian | 模板 | Templater |
| Obsidian | 查询 | Dataview |
| Obsidian | 版本控制 | obsidian-git |
| Python | 文件解析 | python-frontmatter |
| Python | Embedding | 待定（text-embedding-3 / BGE / GTE） |
| Python | 向量存储 | 待定（Chroma / Qdrant / FAISS） |
| Python | Rerank | 初期余弦排序，后期 cross-encoder |
| Python | LLM | Claude API |

## 参考

- `群友知识库体系_工程复现参考.md` — 原系统逆向分析（本仓库）
- AI 记忆工程 — 记忆系统的分层涌现模型（关联项目）

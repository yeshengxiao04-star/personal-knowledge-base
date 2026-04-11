# 非侵入式注释架构改造设计

> 日期：2026-04-12
> 状态：已确认，待实施

## 背景

原 code_memory Init 管线将 LLM 生成的注释写回源码 docstring（Step 3a writer）。这种侵入式方案只适用于自有项目，无法作为开放产品使用。本次改造将注释与源码解耦——注释外存，以 skeleton 为锚定基本单元。

## 核心决策

| 决策 | 选择 |
|------|------|
| 注释存储位置 | 外部 annotations.json，不修改源码 |
| 锚定机制 | qualified name 为主键 + 三级 hash 做变更检测 |
| 注释格式 | 纯结构化 JSON（非人可读文本） |
| 管线形态 | 三步保持：scan → annotate → index |
| 查询时定位代码 | qname 解析出 file_path + 符号名，文件内搜定义 |

## 新管线数据流

```
Step 1: scan
  输入: 源码目录
  输出: skeleton.json（含 hash）
  性质: 确定性，纯 AST

Step 2: annotate
  输入: skeleton.json + 源码（只读）
  输出: annotations.json（结构化 JSON，按 qualified_name 索引）
  性质: LLM 调用，产物可缓存

Step 3: index
  输入: skeleton.json + annotations.json
  输出: shallow/ 目录
  性质: 确定性，纯合并，无 I/O 到源码
```

### 与旧管线对比

| | 旧管线 | 新管线 |
|---|--------|--------|
| 注释住哪 | 源码 docstring | annotations.json |
| 索引怎么建 | 从已注释源码正则提取 | skeleton + annotations 直接合并 |
| 源码是否被修改 | 是（writer 写回） | 否 |
| 中间产物 | skeleton → plan → 已修改源码 → index | skeleton → annotations → index |
| 重建索引成本 | 重跑 LLM | 只跑 Step 3（毫秒级） |

## 锚定机制

### 日常查询

qualified name 自身编码位置信息：`src.stage2.wds_parser:parse_wds_yaml` → 文件 `src/stage2/wds_parser.py`，符号 `parse_wds_yaml`。打开文件搜符号定义即可，微秒级，无需预存行号。

### 变更检测（Maintain 时）

三种 hash 分级检测 block 级变更：

| hash | 计算内容 | 变了意味着 |
|------|----------|-----------|
| signature_hash | 函数名 + 参数名/类型 + 返回类型 | 接口变了，注释核心（what）可能要更新 |
| body_hash | 去注释去空行的源码 | 实现变了，注释大概率仍有效，标 review |
| call_hash | 排序后的调用列表 | 依赖关系变了，关联指向要更新 |

Module/system 级不加 hash，从 skeleton 结构 diff（文件增删、包增删）即可判断。

### Maintain 决策树

```
re-scan → 新 skeleton diff 旧 skeleton
│
├── QName 存在
│   ├── 三 hash 全匹配 → skip
│   ├── body_hash / call_hash 变 → mark review（低优先级）
│   └── signature_hash 变 → queue re-annotate（高优先级）
│
└── QName 消失
    ├── body_hash 在新 skeleton 中命中 → re-link（rename/move）
    ├── signature_hash 命中 → 候选 re-link，需确认
    └── 都没命中 → archive
```

## Scanner 改造

### Hash 计算

仅 block 级（FunctionInfo / ClassInfo）新增三个字段。

**signature_hash**：
- 函数：`name(param1:annotation,param2:annotation)->return` 的规范化字符串
- 类：`name(bases)[sorted method signatures]`
- SHA-256 截前 16 hex

**body_hash**：
- 读 line_start ~ line_end 的源码
- 去纯注释行和空行
- SHA-256 截前 16 hex

**call_hash**：
- 排序后的 calls 列表 join
- SHA-256 截前 16 hex

### 设计决策

- body 归一化 v1 用"去注释去空行"，不做 AST 归一化。有 false positive 数据再调。
- hash 存在 skeleton.json 的 FunctionInfo / ClassInfo 里，作为代码的结构属性。

## Annotator 改造

### 输出格式

从 docstring 文本改为结构化 JSON。三级别各有字段集。

**System 级字段**：what, components, data_flow, external_deps

**Module 级字段**：what, exposes, depends_on, used_by

**Block 级字段**：what, input, output, boundary, parent

### annotations.json 结构

```json
{
  "project_name": "...",
  "generation_time": "ISO8601",
  "model_used": "kimi-k2",
  "entries": {
    "<qualified_name>": {
      "level": "system|module|block",
      "annotation": { ... }
    }
  },
  "skipped": ["..."],
  "stats": { "system": 1, "module": 5, "block": 120 }
}
```

entries 以 qualified_name 为 key，O(1) 查找。

### Prompt 改动

三个 prompt 模板改为要求 LLM 输出 JSON。`_clean_annotation()` 从"去 markdown"变为"校验 JSON schema + 修正常见 LLM 输出问题"。

## Indexer（替代 extractor）

### 职责

纯合并。输入 skeleton.json + annotations.json，输出 shallow/ 目录。不碰源码。

### 合并逻辑

遍历 skeleton 中所有 function/class/module/system 条目，按 qualified_name 在 annotations.json 中查找对应注释，合并结构元数据（file_path、line_range、hash）与注释内容，从 call_graph 反转构建 used_by。

### IndexEntry 格式

```json
{
  "id": "src.stage2.wds_parser:parse_wds_yaml",
  "level": "block",
  "file_path": "src/stage2/wds_parser.py",
  "line_start": 42,
  "line_end": 89,
  "parent_module": "src.stage2",
  "signature_hash": "a1b2c3d4e5f6g7h8",
  "body_hash": "i9j0k1l2m3n4o5p6",
  "call_hash": "q7r8s9t0u1v2w3x4",
  "annotation": {
    "what": "Parse WDS YAML string into WDSWorkflow model",
    "input": {"yaml_str": "raw YAML content", "strict": "enable strict validation"},
    "output": "WDSWorkflow",
    "boundary": "Raises WDSParseError on malformed YAML",
    "parent": "src.stage2"
  },
  "used_by": ["src.stage3.dify_mapper:transform"],
  "depends_on": ["yaml.safe_load", "src.models.wds:WDSWorkflow"]
}
```

Module/system 级 IndexEntry 无 hash 字段，annotation 内字段集按级别不同。

### 输出文件

```
shallow/
├── system.json
├── modules.json
├── blocks.json
└── call_graph.json
```

## 数据模型变更

### 新增/修改

- **FunctionInfo / ClassInfo**：新增 signature_hash, body_hash, call_hash 字段
- **AnnotationEntry**：重新定义为 qualified_name + level + annotation(dict)，移除 file_path, target_name, action, line_hint, content(text)
- **AnnotationPlan → AnnotationStore**：entries 从 list 改为 dict[str, AnnotationEntry]
- **IndexEntry**：新增 hash 字段，annotation 从 text 改为 dict
- **新增 TypedDict**：SystemAnnotation, ModuleAnnotation, BlockAnnotation 定义各级别字段集

### 不变

Skeleton, FileInfo, PackageInfo, ParameterInfo, ShallowIndex 结构不变。

## 物理文件变更

| 文件 | 动作 | 说明 |
|------|------|------|
| `init/writer.py` | 删除 | 不再写回源码 |
| `init/extractor.py` | 重命名为 `init/indexer.py` | 职责从正则提取变为 dict 合并 |
| `init/scanner.py` | 修改 | 新增 hash 计算 |
| `init/annotator.py` | 修改 | 输出 JSON，prompt 要求 JSON |
| `models.py` | 修改 | 模型变更如上 |
| `llm/prompts/*.py` | 修改 | 三个模板改为要求 JSON 输出 |
| `cli.py` | 修改 | 移除 --step write，--step extract 重命名为 --step index |

## CLI 变更

```bash
# 移除
--step write                    # 不再有写回步骤

# 重命名
--step extract → --step index   # 与文件名对齐

# 保留不变
python -m code_memory scan <path>                   # 只跑 Step 1
python -m code_memory init <path> --step annotate   # 跑到 Step 2
python -m code_memory init <path> --step index      # 跑到 Step 3
python -m code_memory init <path>                   # 全量三步
python -m code_memory init <path> --no-llm          # 只跑 Step 1
python -m code_memory init <path> --dry-run         # 只生成 annotation，不建索引
```

## Config 变更

config.yaml 结构不变。`annotation.overwrite_existing` 语义微调：从"是否覆盖源码中已有 docstring"变为"是否覆盖 annotations.json 中已有条目"。

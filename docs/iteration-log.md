# Iteration Log

## 2026-04-12T22:00 — 非侵入式注释架构改造

**变更模块**: `code_memory/models.py`、`code_memory/init/scanner.py`、`code_memory/init/annotator.py`、`code_memory/init/indexer.py`（新建）、`code_memory/cli.py`、`code_memory/llm/prompts/system_annotation.py`、`code_memory/llm/prompts/module_annotation.py`、`code_memory/llm/prompts/block_annotation.py`、`code_memory/init/writer.py`（删除）、`code_memory/init/extractor.py`（删除）
**变更类型**: 重构
**测试**: 24 passed（+24 new）
**设计文档**: `docs/2026-04-12-non-invasive-annotation-design.md`
**实现计划**: `docs/2026-04-12-non-invasive-annotation-plan.md`

**动机**: 原 Init 管线将 LLM 生成的注释写回源码 docstring（writer 步骤）。侵入式方案只适用于自有项目，无法作为开放产品使用。需要将注释与源码解耦——注释外存，以 skeleton 为锚定基本单元。

**核心方案**: 注释存入外部 `annotations.json`（结构化 JSON，按 qualified_name 索引），不修改源码。查询时 qname 自身编码位置信息（`src.stage2.wds_parser:parse_wds_yaml` → 文件 `src/stage2/wds_parser.py`，符号 `parse_wds_yaml`），打开文件搜定义即可。三级 hash（signature/body/call）做 Maintain 阶段变更检测。

**具体内容**:

1. **数据模型重构**（`models.py`）：
   - `FunctionInfo` / `ClassInfo` 新增 `signature_hash`、`body_hash`、`call_hash` 字段
   - 新增 TypedDict：`SystemAnnotation`、`ModuleAnnotation`、`BlockAnnotation` 定义各级别注释字段集
   - `AnnotationEntry` 重定义：`qualified_name` + `level` + `annotation(dict)`，移除旧字段（file_path, target_name, content, action, line_hint）
   - `AnnotationPlan` → `AnnotationStore`：entries 从 list 改为 `dict[str, AnnotationEntry]`
   - `IndexEntry` 新增 hash 字段，`annotation` 从 `str` 改为 `Optional[dict]`

2. **Scanner hash 计算**（`scanner.py`）：
   - `_compute_signature_hash(func)` — 函数签名规范化后 SHA-256 截前 16 hex
   - `_compute_class_signature_hash(cls)` — 类名+基类+排序方法签名
   - `_compute_body_hash(source_lines, start, end)` — 去注释去空行后哈希
   - `_compute_call_hash(calls)` — 排序后调用列表哈希
   - 集成到 `_analyze_file`，methods 先于 class 计算（class hash 依赖 method hash）

3. **Prompt 模板改为 JSON 输出**（三个 prompt 文件）：
   - system: `{what, components, data_flow, external_deps}`
   - module: `{what, exposes, depends_on, used_by}`
   - block: `{what, input, output, boundary, parent}`
   - 均以"只输出 JSON 对象"结尾

4. **Annotator 重构**（`annotator.py`）：
   - 输出 `AnnotationStore`（结构化 JSON），不再生成文本 docstring
   - 新增 `_parse_json_response()` 处理 LLM 返回的 JSON（含 markdown 包裹、前缀文字等容错）
   - 支持 `existing: Optional[AnnotationStore]` 增量更新
   - 移除 `_clean_annotation`、`_find_system_init`、`_has_existing_annotation`

5. **Indexer 新建**（`indexer.py`，替代 `extractor.py`）：
   - `build_index(skeleton, annotations) → ShallowIndex` — 纯合并，无源码 I/O
   - 遍历 skeleton 条目，按 qname 查 annotations，合并元数据 + hash + 注释
   - `_populate_used_by()` 反转调用图构建 used_by

6. **CLI 适配**（`cli.py`）：
   - `--step` choices 移除 `write`/`extract`，新增 `index`
   - 移除 writer 调用，extractor → `build_index`
   - 序列化/反序列化适配 AnnotationStore

7. **删除文件**: `writer.py`（204 行）、`extractor.py`（228 行）

**新增测试**（4 文件，24 tests）：

| 文件 | 数量 | 覆盖 |
|------|------|------|
| `tests/test_models.py`（新建） | 5 | TypedDict 字段集、AnnotationStore 结构、IndexEntry hash 字段 |
| `tests/test_scanner.py`（新建） | 8 | signature/body/call hash 计算、class hash、空输入 |
| `tests/test_annotator.py`（新建） | 6 | JSON 解析容错、AnnotationStore 生成、overwrite 检查 |
| `tests/test_indexer.py`（新建） | 5 | skeleton+annotations 合并、used_by 反转、缺失注释处理 |

**设计决策**:
- qualified name 自身编码位置信息，查询时无需预存行号，打开文件搜符号定义即可（微秒级）
- 三级 hash 仅用于 Maintain 阶段变更检测，不用于查询定位
- body 归一化 v1 用"去注释去空行"，不做 AST 归一化（有 false positive 数据再调）
- SHA-256 截前 16 hex（碰撞概率 ~10⁻¹⁹，远低于需求）
- 注释格式选纯结构化 JSON 而非人可读文本，优先代码化处理和 AI 读取
- 保持三步管线（scan → annotate → index）而非压缩为两步，保留可调试空间和 LLM 结果缓存能力

**影响范围**: Init 管线全部三步。Maintain / Use 阶段尚未实现，不受影响。CLI 接口有 breaking change（`--step write`/`--step extract` 移除）。

---

## 2026-04-13T00:30 — LLM Client 防御性改造 + VWS 实战验证

**变更模块**: `code_memory/llm/client.py`、`code_memory/init/annotator.py`、`code_memory/cli.py`、`code_memory/config.py`、`code_memory/init/indexer.py`
**变更类型**: 增强 + 修复
**测试**: 24 passed

**动机**: 对 Vibe_Workflow_Studio（105 文件、20K LOC）进行首次 Init 实战验证。发现两类问题：(1) Kimi Code API 偶发挂死导致管线阻断，进度全丢；(2) 系统级注释 qname 与 root module qname 冲突，system_count 始终为 0。

**核心方案**: LLM 调用层加防御性编程（timeout + 重试 + 容错 + 增量写盘），system qname 改用 `__system__:` 前缀避免冲突。

**具体内容**:

1. **LLM Client 多协议支持 + 超时控制**（`client.py`）：
   - 新增 Anthropic 协议支持（`api_format: "anthropic"`），与 OpenAI 协议并存
   - 单请求 timeout 90 秒（`float` 直传 SDK），connect timeout 10 秒
   - `max_retries=2`，超时/网络错误自动重试

2. **Config 扩展**（`config.py`）：
   - `LLMConfig` 新增 `api_format: str = "openai"` 字段，支持 `"openai"` 和 `"anthropic"` 两种协议

3. **Annotator 防御性改造**（`annotator.py`）：
   - `_safe_generate()` 包裹所有 LLM 调用：捕获任意异常，记 warning 跳过，不阻断管线
   - `save_callback` 参数：每生成一条注释即回调写盘，支持增量持久化
   - 进度日志：`Module [3/19]: app`、`File [42/105]: stage2.wds_parser`
   - system qname 改为 `__system__:<project_name>`，不再与 root module 冲突

4. **CLI 增量写盘**（`cli.py`）：
   - `_save_incremental(store)` 回调传给 annotator，每条注释生成后写 `annotations.json`
   - 中途崩溃/超时不丢已有进度，重跑自动跳过已完成条目

5. **Indexer 修复**（`indexer.py`）：
   - system 注释查找改为 `__system__:<project_name>` 前缀
   - 包遍历不再混淆 system/module level，system 单独处理

**发现的问题与修复过程**:

| 问题 | 原因 | 修复 |
|------|------|------|
| 管线卡死 35 分钟 | Kimi Code API 偶发不响应 + Anthropic SDK 默认 read timeout 600s | 改传 `float(90)` + `_safe_generate` 兜底 |
| httpx.Timeout 不生效 | Anthropic SDK `timeout` 参数期望 `float`，传 `httpx.Timeout` 对象被忽略 | 改为 `float(self.REQUEST_TIMEOUT)` |
| 进度全丢 | annotator 跑完才一次性写 annotations.json | 改为 `save_callback` 每条写盘 |
| system_count: 0 | `_find_system_qname` 返回 `""`（root module_path），module 级注释同 key 覆盖 | system qname 改为 `__system__:vibe-workflow` |
| `python` 命令不存在 | macOS 只有 `python3` | 全部改用 `python3` |
| openai/anthropic 包缺失 | 系统 Python 未安装 | `pip3 install --break-system-packages` |

**VWS 实战验证结果**:

| 指标 | 数值 |
|------|------|
| 扫描文件 | 105 |
| 总行数 | 20,799 |
| LLM 调用次数 | 434（1 system + 19 module + 414 block） |
| 跳过（私有/短函数） | 257 |
| 失败 | 0 |
| 注释覆盖率 | 434/691 = 63% |
| 产出体积 | skeleton 772K + annotations 289K + shallow index 653K |
| 耗时 | ~45 分钟（串行，含一次中断续跑） |

**设计决策**:
- timeout 传 `float` 而非 `httpx.Timeout`，兼容 Anthropic/OpenAI 两家 SDK
- 增量写盘每条都写（非批量），牺牲少量 I/O 换取最大进度保全
- `_safe_generate` 在 annotator 层而非 client 层，保持 client 的异常语义清晰
- system qname 用 `__system__:` 前缀而非项目名，因为项目名可能与某个包名冲突

**后续方向**: LLM 调用并发化（asyncio + Semaphore），从 45 分钟压缩到 3-5 分钟。依赖关系分析已完成：system 串行 → module 全并发 → block 全并发。

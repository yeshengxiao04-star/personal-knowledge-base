"""CLI 入口。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from .config import ProjectConfig


def main():
    parser = argparse.ArgumentParser(
        prog="code_memory",
        description="代码项目记忆系统 — 为代码项目构建外部挂载的记忆知识库",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    subparsers = parser.add_subparsers(dest="command")

    # init 子命令
    init_parser = subparsers.add_parser("init", help="初始化：全量注释生成 + 索引构建")
    init_parser.add_argument("project_path", type=Path, help="项目根目录路径")
    init_parser.add_argument("--config", type=Path, help="配置文件路径 (config.yaml)")
    init_parser.add_argument("--output", type=Path, help="记忆库输出目录（默认旁挂）")
    init_parser.add_argument("--step", choices=["scan", "annotate", "write", "extract", "all"],
                            default="all", help="只执行指定步骤")
    init_parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 注释，只做静态分析")
    init_parser.add_argument("--dry-run", action="store_true", help="不写回文件，只输出注释清单")

    # scan 子命令（便捷方式，等同 init --step scan）
    scan_parser = subparsers.add_parser("scan", help="仅执行静态分析，输出骨架文件")
    scan_parser.add_argument("project_path", type=Path, help="项目根目录路径")
    scan_parser.add_argument("--config", type=Path, help="配置文件路径")
    scan_parser.add_argument("--output", type=Path, help="skeleton.json 输出路径")

    args = parser.parse_args()

    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.command == "scan":
        _run_scan(args)
    elif args.command == "init":
        _run_init(args)
    else:
        parser.print_help()
        sys.exit(1)


def _run_scan(args):
    """只运行静态分析。"""
    from .init.scanner import scan_project

    config = _load_config(args)
    logging.info(f"Scanning project: {config.project_root}")

    skeleton = scan_project(config)

    # 输出
    output_path = args.output or _default_memory_dir(args.project_path) / "skeleton.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(skeleton), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logging.info(f"Skeleton written to: {output_path}")
    logging.info(f"Stats: {skeleton.stats}")


def _run_init(args):
    """运行完整 init 流程或指定步骤。"""
    from .init.scanner import scan_project

    config = _load_config(args)
    memory_dir = args.output or _default_memory_dir(args.project_path)
    memory_dir.mkdir(parents=True, exist_ok=True)

    step = args.step

    # Step 1: 静态分析
    if step in ("scan", "all"):
        logging.info("Step 1: Static analysis...")
        skeleton = scan_project(config)
        skeleton_path = memory_dir / "skeleton.json"
        skeleton_path.write_text(
            json.dumps(asdict(skeleton), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logging.info(f"  Skeleton: {skeleton.stats}")
    else:
        # 从已有骨架加载
        skeleton_path = memory_dir / "skeleton.json"
        if not skeleton_path.exists():
            logging.error("skeleton.json not found. Run scan first.")
            sys.exit(1)
        from .models import Skeleton
        skeleton = _load_skeleton(skeleton_path)

    if args.no_llm or step == "scan":
        logging.info("Done (--no-llm or --step scan)")
        return

    # Step 2: LLM 注释生成
    if step in ("annotate", "all"):
        logging.info("Step 2: LLM annotation generation...")
        from .init.annotator import generate_annotations
        plan = generate_annotations(skeleton, config)
        plan_path = memory_dir / "annotation_plan.json"
        plan_path.write_text(
            json.dumps(asdict(plan), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logging.info(f"  Plan: {plan.stats}")
    else:
        plan_path = memory_dir / "annotation_plan.json"
        if not plan_path.exists():
            logging.error("annotation_plan.json not found. Run annotate first.")
            sys.exit(1)
        plan = _load_plan(plan_path)

    if args.dry_run or step == "annotate":
        logging.info("Done (--dry-run or --step annotate)")
        return

    # Step 3a: 写回
    if step in ("write", "all"):
        logging.info("Step 3a: Writing annotations back to source files...")
        from .init.writer import write_annotations
        write_stats = write_annotations(plan, Path(config.project_root))
        logging.info(f"  Write stats: {write_stats}")

    # Step 3b: 提取索引
    if step in ("extract", "all"):
        logging.info("Step 3b: Extracting index from annotated code...")
        from .init.extractor import extract_index
        index = extract_index(config)

        # 写出索引文件
        shallow_dir = memory_dir / "shallow"
        shallow_dir.mkdir(exist_ok=True)

        _write_index_files(index, shallow_dir)
        logging.info(f"  Index: {index.stats}")

    logging.info("Init complete.")


def _load_config(args) -> ProjectConfig:
    """加载配置。"""
    project_path = args.project_path.resolve()

    if hasattr(args, "config") and args.config:
        config = ProjectConfig.from_yaml(args.config)
        config.project_root = str(project_path)
    else:
        config = ProjectConfig.default_for_project(project_path)

    # 自动检测 source_dirs
    if config.source_dirs == ["src"]:
        # 检查常见目录结构
        for candidate in ["src", "lib", project_path.name]:
            if (project_path / candidate).is_dir():
                config.source_dirs = [candidate]
                break

    config.project_root = str(project_path)
    return config


def _default_memory_dir(project_path: Path) -> Path:
    """计算默认的旁挂记忆库目录。"""
    project_path = project_path.resolve()
    return project_path.parent / f".{project_path.name}-memory"


def _load_skeleton(path: Path):
    """从 JSON 加载 Skeleton。简化版，不做完整反序列化。"""
    import json
    from .models import Skeleton, FileInfo, PackageInfo, FunctionInfo, ClassInfo, ParameterInfo, BlockKind

    data = json.loads(path.read_text(encoding="utf-8"))

    files = []
    for fd in data.get("files", []):
        functions = []
        for fn in fd.get("functions", []):
            params = [ParameterInfo(**p) for p in fn.get("parameters", [])]
            fn_obj = FunctionInfo(
                name=fn["name"], qualified_name=fn["qualified_name"],
                kind=BlockKind(fn["kind"]), line_start=fn["line_start"],
                line_end=fn["line_end"], parameters=params,
                return_annotation=fn.get("return_annotation"),
                docstring=fn.get("docstring"), decorators=fn.get("decorators", []),
                calls=fn.get("calls", []),
            )
            functions.append(fn_obj)

        classes = []
        for cd in fd.get("classes", []):
            methods = []
            for m in cd.get("methods", []):
                m_params = [ParameterInfo(**p) for p in m.get("parameters", [])]
                methods.append(FunctionInfo(
                    name=m["name"], qualified_name=m["qualified_name"],
                    kind=BlockKind(m["kind"]), line_start=m["line_start"],
                    line_end=m["line_end"], parameters=m_params,
                    return_annotation=m.get("return_annotation"),
                    docstring=m.get("docstring"), decorators=m.get("decorators", []),
                    calls=m.get("calls", []),
                ))
            classes.append(ClassInfo(
                name=cd["name"], qualified_name=cd["qualified_name"],
                line_start=cd["line_start"], line_end=cd["line_end"],
                docstring=cd.get("docstring"), bases=cd.get("bases", []),
                methods=methods, decorators=cd.get("decorators", []),
            ))

        files.append(FileInfo(
            file_path=fd["file_path"], module_path=fd["module_path"],
            docstring=fd.get("docstring"), imports=fd.get("imports", []),
            all_exports=fd.get("all_exports"), functions=functions,
            classes=classes, line_count=fd.get("line_count", 0),
        ))

    packages = [PackageInfo(**pd) for pd in data.get("packages", [])]

    return Skeleton(
        project_name=data["project_name"],
        project_root=data["project_root"],
        source_dirs=data["source_dirs"],
        scan_time=data["scan_time"],
        files=files, packages=packages,
        call_graph=data.get("call_graph", {}),
        stats=data.get("stats", {}),
    )


def _load_plan(path: Path):
    """从 JSON 加载 AnnotationPlan。"""
    import json
    from .models import AnnotationPlan, AnnotationEntry, AnnotationLevel

    data = json.loads(path.read_text(encoding="utf-8"))
    entries = [
        AnnotationEntry(
            file_path=e["file_path"], target_name=e["target_name"],
            level=AnnotationLevel(e["level"]), content=e["content"],
            action=e.get("action", "insert"), line_hint=e.get("line_hint"),
        )
        for e in data.get("entries", [])
    ]
    return AnnotationPlan(
        project_name=data["project_name"],
        generation_time=data["generation_time"],
        model_used=data["model_used"],
        entries=entries,
        skipped=data.get("skipped", []),
        stats=data.get("stats", {}),
    )


def _write_index_files(index, shallow_dir: Path):
    """将索引写入文件。"""
    from dataclasses import asdict

    system_path = shallow_dir / "system.json"
    modules_path = shallow_dir / "modules.json"
    blocks_path = shallow_dir / "blocks.json"
    call_graph_path = shallow_dir / "call_graph.json"

    system_path.write_text(
        json.dumps([asdict(e) for e in index.system_entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    modules_path.write_text(
        json.dumps([asdict(e) for e in index.module_entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    blocks_path.write_text(
        json.dumps([asdict(e) for e in index.block_entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    call_graph_path.write_text(
        json.dumps(index.call_graph, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

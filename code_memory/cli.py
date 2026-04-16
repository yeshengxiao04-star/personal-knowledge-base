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
    init_parser.add_argument(
        "--step", choices=["scan", "annotate", "index", "all"],
        default="all", help="只执行指定步骤",
    )
    init_parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 注释，只做静态分析")
    init_parser.add_argument("--dry-run", action="store_true", help="不建索引，只输出注释")

    # scan 子命令（便捷方式）
    scan_parser = subparsers.add_parser("scan", help="仅执行静态分析，输出骨架文件")
    scan_parser.add_argument("project_path", type=Path, help="项目根目录路径")
    scan_parser.add_argument("--config", type=Path, help="配置文件路径")
    scan_parser.add_argument("--output", type=Path, help="skeleton.json 输出路径")

    args = parser.parse_args()

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
        skeleton_path = memory_dir / "skeleton.json"
        if not skeleton_path.exists():
            logging.error("skeleton.json not found. Run scan first.")
            sys.exit(1)
        skeleton = _load_skeleton(skeleton_path)

    if args.no_llm or step == "scan":
        logging.info("Done (--no-llm or --step scan)")
        return

    # Step 2: LLM 注释生成
    if step in ("annotate", "all"):
        logging.info("Step 2: LLM annotation generation...")
        from .init.annotator import generate_annotations

        # 加载已有注释（用于 overwrite_existing 检查 + 增量续跑）
        annotations_path = memory_dir / "annotations.json"
        existing = _load_annotations(annotations_path) if annotations_path.exists() else None

        def _save_incremental(store):
            """每条注释生成后增量写盘，防止中途崩溃丢失进度。"""
            annotations_path.write_text(
                json.dumps(_annotation_store_to_dict(store), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        annotations = generate_annotations(
            skeleton, config, existing=existing, save_callback=_save_incremental,
        )
        _save_incremental(annotations)  # 最终写入含 stats
        logging.info(f"  Annotations: {annotations.stats}")
    else:
        annotations_path = memory_dir / "annotations.json"
        if not annotations_path.exists():
            logging.error("annotations.json not found. Run annotate first.")
            sys.exit(1)
        annotations = _load_annotations(annotations_path)

    if args.dry_run or step == "annotate":
        logging.info("Done (--dry-run or --step annotate)")
        return

    # Step 3: 构建索引
    if step in ("index", "all"):
        logging.info("Step 3: Building index...")
        from .init.indexer import build_index

        index = build_index(skeleton, annotations)

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

    if config.source_dirs == ["src"]:
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
    """从 JSON 加载 Skeleton。"""
    from .models import (
        Skeleton, FileInfo, PackageInfo, FunctionInfo, ClassInfo,
        ParameterInfo, BlockKind,
    )

    data = json.loads(path.read_text(encoding="utf-8"))

    files = []
    for fd in data.get("files", []):
        functions = []
        for fn in fd.get("functions", []):
            params = [ParameterInfo(**p) for p in fn.get("parameters", [])]
            functions.append(FunctionInfo(
                name=fn["name"], qualified_name=fn["qualified_name"],
                kind=BlockKind(fn["kind"]), line_start=fn["line_start"],
                line_end=fn["line_end"], parameters=params,
                return_annotation=fn.get("return_annotation"),
                docstring=fn.get("docstring"), decorators=fn.get("decorators", []),
                calls=fn.get("calls", []),
                signature_hash=fn.get("signature_hash", ""),
                body_hash=fn.get("body_hash", ""),
                call_hash=fn.get("call_hash", ""),
            ))

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
                    signature_hash=m.get("signature_hash", ""),
                    body_hash=m.get("body_hash", ""),
                    call_hash=m.get("call_hash", ""),
                ))
            classes.append(ClassInfo(
                name=cd["name"], qualified_name=cd["qualified_name"],
                line_start=cd["line_start"], line_end=cd["line_end"],
                docstring=cd.get("docstring"), bases=cd.get("bases", []),
                methods=methods, decorators=cd.get("decorators", []),
                signature_hash=cd.get("signature_hash", ""),
                body_hash=cd.get("body_hash", ""),
                call_hash=cd.get("call_hash", ""),
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


def _load_annotations(path: Path):
    """从 JSON 加载 AnnotationStore。"""
    from .models import AnnotationStore, AnnotationEntry, AnnotationLevel

    data = json.loads(path.read_text(encoding="utf-8"))
    entries = {}
    for qname, ed in data.get("entries", {}).items():
        entries[qname] = AnnotationEntry(
            qualified_name=qname,
            level=AnnotationLevel(ed["level"]),
            annotation=ed["annotation"],
        )
    return AnnotationStore(
        project_name=data["project_name"],
        generation_time=data["generation_time"],
        model_used=data["model_used"],
        entries=entries,
        skipped=data.get("skipped", []),
        stats=data.get("stats", {}),
    )


def _annotation_store_to_dict(store) -> dict:
    """将 AnnotationStore 序列化为可 JSON 化的 dict。"""
    return {
        "project_name": store.project_name,
        "generation_time": store.generation_time,
        "model_used": store.model_used,
        "entries": {
            qname: {
                "level": entry.level.value,
                "annotation": entry.annotation,
            }
            for qname, entry in store.entries.items()
        },
        "skipped": store.skipped,
        "stats": store.stats,
    }


def _write_index_files(index, shallow_dir: Path):
    """将索引写入文件。"""
    from dataclasses import asdict

    (shallow_dir / "system.json").write_text(
        json.dumps([asdict(e) for e in index.system_entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (shallow_dir / "modules.json").write_text(
        json.dumps([asdict(e) for e in index.module_entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (shallow_dir / "blocks.json").write_text(
        json.dumps([asdict(e) for e in index.block_entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (shallow_dir / "call_graph.json").write_text(
        json.dumps(index.call_graph, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

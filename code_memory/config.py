"""加载和管理配置。"""

from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class LLMConfig:
    model: str = "kimi-k2"
    api_base: Optional[str] = None
    api_key_env: str = "LLM_API_KEY"  # 环境变量名
    api_format: str = "openai"  # "openai" 或 "anthropic"
    temperature: float = 0.3
    max_tokens: int = 2000


@dataclass
class AnnotationConfig:
    overwrite_existing: bool = False
    min_function_lines: int = 3


@dataclass
class ProjectConfig:
    project_name: str = ""
    project_root: str = ""
    source_dirs: list[str] = field(default_factory=lambda: ["src"])
    exclude_patterns: list[str] = field(
        default_factory=lambda: ["__pycache__", ".git", ".venv", "node_modules"]
    )
    llm: LLMConfig = field(default_factory=LLMConfig)
    annotation: AnnotationConfig = field(default_factory=AnnotationConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> "ProjectConfig":
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        llm_data = data.pop("llm", {})
        annotation_data = data.pop("annotation", {})

        config = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        config.llm = LLMConfig(**{k: v for k, v in llm_data.items() if k in LLMConfig.__dataclass_fields__})
        config.annotation = AnnotationConfig(
            **{k: v for k, v in annotation_data.items() if k in AnnotationConfig.__dataclass_fields__}
        )
        return config

    @classmethod
    def default_for_project(cls, project_path: Path) -> "ProjectConfig":
        return cls(
            project_name=project_path.name,
            project_root=str(project_path),
        )

    def resolve_project_root(self, config_dir: Path) -> Path:
        """解析 project_root 相对路径（相对于配置文件所在目录）。"""
        root = Path(self.project_root)
        if not root.is_absolute():
            root = (config_dir / root).resolve()
        return root

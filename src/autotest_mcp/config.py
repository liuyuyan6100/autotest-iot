"""配置加载：从 YAML 读 server/tools/boards，token 等敏感项允许 env 覆盖。

网络层刻意不绑 tailscale：host/token/mTLS 都是普通配置项，家用与公司部署用同一份代码。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ButtonConfig(BaseModel):
    relay: int


class BoardConfig(BaseModel):
    port: str
    baud: int = 115200
    buttons: dict[str, ButtonConfig] = Field(default_factory=dict)
    power_relay: int | None = None


class MTlsConfig(BaseModel):
    enabled: bool = False
    server_cert: str = ""
    server_key: str = ""
    client_ca: str = ""


class ServerConfig(BaseModel):
    transport: Literal["http", "stdio"] = "http"
    host: str = "0.0.0.0"
    port: int = 8787
    token: str = ""
    board_lock_policy: Literal["queue", "reject"] = "queue"
    mtls: MTlsConfig = Field(default_factory=MTlsConfig)


class ToolsConfig(BaseModel):
    idf_version: str = "v5.3"
    addr2line: str = ""
    builder_backend: Literal["docker", "local"] = "docker"


class McpClientConfig(BaseModel):
    """编排器侧连接硬件网关的配置。家用填 tailscale URL，公司填内网 URL。"""

    url: str = "http://localhost:8787/mcp"
    token: str = ""


class AgentConfig(BaseModel):
    model: str = "claude-opus-4-8"
    effort: str = "high"
    # 测试模式串口命令白名单：ReproPlanner 产出的 inject 命令必须命中此前缀之一
    test_command_whitelist: list[str] = Field(
        default_factory=lambda: ["test> ", "log> ", "repro> "]
    )


class AppConfig(BaseModel):
    boards: dict[str, BoardConfig] = Field(default_factory=dict)
    server: ServerConfig = Field(default_factory=ServerConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    mcp: McpClientConfig = Field(default_factory=McpClientConfig)
    agents: AgentConfig = Field(default_factory=AgentConfig)


class EnvSettings(BaseSettings):
    """少量敏感/部署相关项走环境变量，便于不落盘。"""

    model_config = SettingsConfigDict(env_prefix="AUTOTEST_", extra="ignore")

    config_path: str = "config/boards.yaml"
    token: str = ""  # 覆盖 yaml 里的 server.token


def load_config(path: str | os.PathLike[str] = "config/boards.yaml") -> AppConfig:
    p = Path(path)
    if not p.exists():
        return AppConfig()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return AppConfig(**data)

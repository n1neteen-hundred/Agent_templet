"""
MyClaw 配置管理模块

对应 OpenClaw 的：src/config/config.ts
职责：加载和管理 myclaw.json 配置文件
"""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# 添加项目根目录到 path，以便导入 prompt 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prompt.DEFAULT import SYSTEM_PROMPT as DEFAULT_SYSTEM_PROMPT


# ---------- 配置数据结构 ----------
# 用 dataclass 定义配置的"形状"，就像一份表格的列定义

@dataclass
class AgentConfig:
    """Agent（大厨）的配置"""
    model: str = "claude-sonnet-4-20250514"
    api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    base_url: str = os.environ.get("ANTHROPIC_BASE_URL", "")
    system_prompt: str = DEFAULT_SYSTEM_PROMPT


@dataclass
class GatewayConfig:
    """Gateway（总机）的配置"""
    port: int = 18789


@dataclass
class TelegramConfig:
    """Telegram 通道的配置"""
    enabled: bool = False
    bot_token: str = ""


@dataclass
class WeChatConfig:
    """WeChat 通道的配置"""
    enabled: bool = False
    base_url: str = "https://ilinkai.weixin.qq.com"
    token_path: str = "~/.myclaw/wechat"


@dataclass
class ChannelsConfig:
    """所有通道的配置"""
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    wechat: WeChatConfig = field(default_factory=WeChatConfig)


@dataclass
class SessionConfig:
    """Session（记忆）的配置"""
    store_path: str = "~/.myclaw/sessions"
    max_history: int = 50


@dataclass
class ToolsConfig:
    """工具沙箱的配置"""
    read_dir: str = "~/.myclaw/workspace"
    write_dir: str = "~/.myclaw/workspace/sandbox"


@dataclass
class MyClawConfig:
    """顶层配置，包含所有子配置"""
    agent: AgentConfig = field(default_factory=AgentConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    channels: ChannelsConfig = field(default_factory=ChannelsConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)


# ---------- 配置加载函数 ----------

def load_config(config_path: str | None = None) -> MyClawConfig:
    """
    加载配置文件。

    查找顺序：
    1. 传入的 config_path 参数
    2. 当前目录的 myclaw.json
    3. ~/.myclaw/myclaw.json

    如果都没找到，返回默认配置。
    """
    # 确定配置文件路径
    paths_to_try = []
    if config_path:
        paths_to_try.append(Path(config_path))
    paths_to_try.append(Path("myclaw.json"))
    paths_to_try.append(Path.home() / ".myclaw" / "myclaw.json")

    # 尝试每个路径
    for path in paths_to_try:
        if path.exists():
            return _parse_config_file(path)

    # 都没找到，报错提醒用户创建配置文件
    raise FileNotFoundError(
        "未找到 myclaw.json 配置文件！\n"
        "请复制 myclaw.example.json 为 myclaw.json 并填写配置：\n"
        "  cp myclaw.example.json myclaw.json"
    )


def _parse_config_file(path: Path) -> MyClawConfig:
    """解析 JSON 配置文件为 MyClawConfig 对象"""
    print(f"[config] 加载配置文件: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    config = MyClawConfig()

    # 解析 agent 配置
    if "agent" in raw:
        ag = raw["agent"]
        config.agent = AgentConfig(
            model=ag.get("model", config.agent.model),
            api_key=ag.get("api_key", config.agent.api_key),
            base_url=ag.get("base_url", config.agent.base_url),
            system_prompt=ag.get("system_prompt", config.agent.system_prompt),
        )

    # 解析 gateway 配置
    if "gateway" in raw:
        gw = raw["gateway"]
        config.gateway = GatewayConfig(
            port=gw.get("port", config.gateway.port),
        )

    # 解析 channels 配置
    if "channels" in raw:
        ch = raw["channels"]
        if "telegram" in ch:
            tg = ch["telegram"]
            config.channels.telegram = TelegramConfig(
                enabled=tg.get("enabled", False),
                bot_token=tg.get("bot_token", ""),
            )
        if "wechat" in ch:
            wx = ch["wechat"]
            config.channels.wechat = WeChatConfig(
                enabled=wx.get("enabled", False),
                base_url=wx.get("base_url", config.channels.wechat.base_url),
                token_path=wx.get("token_path", config.channels.wechat.token_path),
            )

    # 解析 tools 配置
    if "tools" in raw:
        tl = raw["tools"]
        config.tools = ToolsConfig(
            read_dir=tl.get("read_dir", config.tools.read_dir),
            write_dir=tl.get("write_dir", config.tools.write_dir),
        )

    # 解析 session 配置
    if "session" in raw:
        ss = raw["session"]
        config.session = SessionConfig(
            store_path=ss.get("store_path", config.session.store_path),
            max_history=ss.get("max_history", config.session.max_history),
        )

    return config

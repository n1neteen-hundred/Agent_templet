"""
MyClaw Gateway 模块

对应 OpenClaw 的：src/gateway/server.impl.ts
职责：中央管理器，管理所有子系统的生命周期，处理消息路由

"""

import asyncio
from config import MyClawConfig, load_config
from session import SessionStore
from agents.agent import Agent
from channels import BaseChannel
from tools import tools


class Gateway:
    """
    中央管理器 — 整个系统的心脏。

    对应 OpenClaw 的 startGatewayServer()。
    它把 Config、Agent、Session、Channels 全部连接起来。
    """

    def __init__(self, config: MyClawConfig):
        self.config = config

        # 初始化各个子系统
        tools.configure(
            read_dir=config.tools.read_dir,
            write_dir=config.tools.write_dir,
        )
        self.session_store = SessionStore(
            store_path=config.session.store_path,
            max_history=config.session.max_history,
        )
        self.agent = Agent(config.agent)
        self.channels: dict[str, BaseChannel] = {}

        self._running = False
        print(f"[gateway] 初始化完成，端口: {config.gateway.port}")

    def register_channel(self, channel: BaseChannel) -> None:
        """
        注册一个通道。
        """
        channel.set_message_handler(self.handle_message)
        self.channels[channel.name] = channel
        print(f"[gateway] 注册通道: {channel.name}")

    async def handle_message(self, channel: str, sender: str, text: str) -> str:
        """
        处理一条收到的消息 — 这是核心路由逻辑。

        消息流：Channel 收到消息 → 调用这个方法 → Agent 处理 → 返回回复

        对应 OpenClaw 中整个 消息 → auto-reply → agent → 回复 的链路。

        参数:
            channel: 消息来自哪个通道（如 "telegram"）
            sender: 发送者 ID
            text: 消息文本

        返回:
            AI 的回复文本
        """
        # 1. 生成 session key（通道名 + 发送者 = 唯一的对话）
        session_key = f"{channel}-{sender}"
        print(f"[gateway] 收到消息 [{session_key}]: {text[:50]}...")

        # 2. 获取对话历史
        session = self.session_store.get(session_key)

        # 3. 让 Agent 处理
        reply = await self.agent.run(text, session)

        # 4. 保存对话历史
        self.session_store.save(session_key)

        print(f"[gateway] 回复 [{session_key}]: {reply[:50]}...")
        return reply

    async def start(self) -> None:
        """
        启动 Gateway — 启动所有子系统。

        对应 OpenClaw 中 startGatewayServer() 的启动序列。
        """
        self._running = True
        print("[gateway] 正在启动...")

        # 启动所有注册的通道
        for name, channel in self.channels.items():
            try:
                await channel.start()
                print(f"[gateway] 通道 {name} 启动成功")
            except Exception as e:
                print(f"[gateway] 通道 {name} 启动失败: {e}")

        print("[gateway] ✅ 启动完成！")

    async def stop(self) -> None:
        """停止 Gateway — 关闭所有子系统"""
        self._running = False
        print("[gateway] 正在关闭...")

        for name, channel in self.channels.items():
            try:
                await channel.stop()
            except Exception as e:
                print(f"[gateway] 通道 {name} 关闭失败: {e}")

        print("[gateway] 已关闭")

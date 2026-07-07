"""
MyClaw Channel 基类定义

对应 OpenClaw 的：src/channels/plugins/types.ts
职责：定义所有通道必须实现的接口（抽象基类）

每个通道（Telegram、Slack 等）都是这个基类的子类。
"""

from abc import ABC, abstractmethod
from typing import Callable, Awaitable


# 消息处理回调的类型：
# 当通道收到消息时，调用这个函数把消息交给 Gateway
# 参数: (channel_name, sender_id, message_text)
# 返回: AI 的回复文本
MessageHandler = Callable[[str, str, str], Awaitable[str]]


class BaseChannel(ABC):
    """
    通道基类 — 所有通道都要继承它并实现这些方法。

    对应 OpenClaw 的 ChannelPlugin 接口。
    就像一份"服务员守则"，每个服务员都要会这些技能。
    """

    def __init__(self, name: str):
        self.name = name
        self._message_handler: MessageHandler | None = None

    def set_message_handler(self, handler: MessageHandler) -> None:
        """设置消息处理器（由 Gateway 调用，把回调函数传进来）"""
        self._message_handler = handler

    @abstractmethod
    async def start(self) -> None:
        """启动通道连接（比如登录 Telegram）"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止通道连接"""
        pass

    @abstractmethod
    async def send_message(self, recipient: str, text: str) -> None:
        """发送消息给指定接收者"""
        pass

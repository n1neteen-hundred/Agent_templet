"""
MyClaw 会话管理模块

对应 OpenClaw 的：src/config/sessions.ts + src/gateway/session-utils.ts
职责：管理对话历史，每个 session_key 对应一个对话
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------- 数据结构 ----------

@dataclass
class Message:
    """一条消息"""
    role: str       # "user" | "assistant"
    content: str | list[dict]   # 消息内容


@dataclass
class Session:
    """
    一个对话会话。

    就像一个"笔记本"，记录了你和 AI 之间所有的对话。
    session_key 是这个笔记本的名字（比如 "main" 或 "telegram-张三"）。
    """
    session_key: str
    messages: list[Message] = field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        """添加一条消息到历史"""
        self.messages.append(Message(role=role, content=content))

    def get_messages_for_api(self) -> list[dict[str, str]]:
        """把消息历史转成 API 需要的格式"""
        return [{"role": m.role, "content": m.content} for m in self.messages]

    def trim(self, max_history: int = 20) -> None:
        """只保留最近 max_history 条消息，避免太长"""
        if len(self.messages) > max_history:
            self.messages = self.messages[-max_history:]


class SessionStore:
    """
    管理所有 Session 的仓库。

    - 功能：                                                                                                
        - get(session_key) - 获取/创建 session（有内存缓存）                                                  
        - save(session_key) - 保存到 JSON 文件              
        - reset(session_key) - 清空某个会话  
    """

    def __init__(self, store_path: str, max_history: int = 50):
        self.store_path = Path(os.path.expanduser(store_path))
        self.max_history = max_history
        # 内存缓存，避免每次都读文件
        self._cache: dict[str, Session] = {}

    def get(self, session_key: str) -> Session:
        """获取一个 Session，不存在就创建新的"""
        if session_key in self._cache:
            return self._cache[session_key]

        # 尝试从文件加载
        session = self._load_from_file(session_key)
        if session is None:
            session = Session(session_key=session_key)

        self._cache[session_key] = session
        return session

    def save(self, session_key: str) -> None:
        """保存 Session 到文件"""
        session = self._cache.get(session_key)
        if session is None:
            return

        # 保存前先裁剪
        session.trim(self.max_history)

        # 确保目录存在
        self.store_path.mkdir(parents=True, exist_ok=True)

        file_path = self.store_path / f"{session_key}.json"
        data = {
            "session_key": session.session_key,
            "messages": [{"role": m.role, "content": m.content} for m in session.messages],
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def reset(self, session_key: str) -> None:
        """清空一个 Session 的历史"""
        self._cache[session_key] = Session(session_key=session_key)
        self.save(session_key)
        print(f"[session] 已重置会话: {session_key}")

    def _load_from_file(self, session_key: str) -> Session | None:
        """从文件加载 Session"""
        file_path = self.store_path / f"{session_key}.json"
        if not file_path.exists():
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            session = Session(session_key=session_key)
            for msg in data.get("messages", []):
                session.add_message(msg["role"], msg["content"])
            return session
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[session] 加载会话文件失败: {e}")
            return None

"""
WeChat Channel 独立测试脚本
跳过 gateway/agent，直接测试扫码登录和消息收发

用法: python test_wechat.py
"""

import asyncio
from dataclasses import dataclass

from channels.wechat_channel import WeChatChannel


@dataclass
class FakeWeChatConfig:
    enabled: bool = True
    base_url: str = "https://ilinkai.weixin.qq.com"
    token_path: str = "~/.myclaw/wechat"


async def echo_handler(channel: str, sender: str, text: str) -> str:
    """简单的 echo 回复，用于测试消息收发"""
    print(f"\n📨 收到消息 [{channel}:{sender}]: {text}")
    reply = f"[echo] 你说的是: {text}"
    print(f"📤 回复: {reply}")
    return reply


async def main():
    config = FakeWeChatConfig()
    wechat = WeChatChannel(config)
    wechat.set_message_handler(echo_handler)

    print("=" * 50)
    print("🦞 WeChat Channel 独立测试")
    print("   功能: 扫码登录 + echo 回复")
    print("   按 Ctrl+C 退出")
    print("=" * 50)
    print()

    try:
        await wechat.start()
        # 保持运行
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        print("\n正在关闭...")
    finally:
        await wechat.stop()


if __name__ == "__main__":
    asyncio.run(main())

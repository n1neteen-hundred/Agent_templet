"""
入口模块

用法:
    python main.py run          # 启动 Gateway（后台服务模式）
    python main.py chat         # 终端对话模式（调试用）
    python main.py chat --new   # 清空历史，开始新对话
"""

import argparse
import asyncio
import sys

from config import load_config
from gateway import Gateway


def cmd_chat(args: argparse.Namespace) -> None:
    """
    终端对话模式 — 在命令行直接和 AI 对话。

    这不是 OpenClaw 的功能，而是我们加的调试模式，
    方便在没有 Telegram 的情况下测试 Agent 是否正常工作。
    """
    config = load_config(args.config)

    # 检查 API Key
    if not config.agent.api_key or config.agent.api_key == "YOUR_ANTHROPIC_API_KEY_HERE":
        print("❌ 请先在 myclaw.json 中设置你的 Anthropic API Key！")
        print('   把 "YOUR_ANTHROPIC_API_KEY_HERE" 替换成你的真实 Key')
        sys.exit(1)

    gateway = Gateway(config)

    # 如果 --new 参数，重置会话
    session_key = "cli-main"
    if args.new:
        gateway.session_store.reset(session_key)

    print("=" * 50)
    print("🦞 MyClaw 终端对话模式")
    print(f"   模型: {config.agent.model}")
    print(f"   输入消息开始对话，输入 'quit' 退出")
    print(f"   输入 '/new' 重置对话历史")
    print("=" * 50)
    print()

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！👋")
            break

        if not user_input:
            continue

        if user_input.lower() == "quit":
            print("再见！👋")
            break

        if user_input == "/new":
            gateway.session_store.reset(session_key)
            print("对话已重置 ✨\n")
            continue

        # 调用 Gateway 处理消息（同步版本）
        reply = asyncio.run(gateway.handle_message("cli", "main", user_input))
        print(f"\n🤖: {reply}\n")


def cmd_run(args: argparse.Namespace) -> None:
    """
    启动 Gateway 服务模式。

    对应 OpenClaw 的 `openclaw gateway` 命令。
    启动后会在后台运行，监听各个通道的消息。
    """
    config = load_config(args.config)

    if not config.agent.api_key or config.agent.api_key == "YOUR_ANTHROPIC_API_KEY_HERE":
        print("❌ 请先在 myclaw.json 中设置你的 Anthropic API Key！")
        sys.exit(1)

    gateway = Gateway(config)

    # TODO: 注册启用的通道（目前还没实现 Telegram）
    # if config.channels.telegram.enabled:
    #     from channels.telegram_channel import TelegramChannel
    #     telegram = TelegramChannel(config.channels.telegram)
    #     gateway.register_channel(telegram)

    # 注册 WeChat 通道
    if config.channels.wechat.enabled:
        from channels.wechat_channel import WeChatChannel
        wechat = WeChatChannel(config.channels.wechat)
        gateway.register_channel(wechat)

    print(f"🦞 MyClaw Gateway 启动中... (端口 {config.gateway.port})")

    async def _run_gateway():
        await gateway.start()
        # 保持运行直到被中断
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await gateway.stop()

    try:
        asyncio.run(_run_gateway())
    except KeyboardInterrupt:
        print("\n正在关闭...")


def main() -> None:
    """CLI 入口 — 解析命令行参数"""
    parser = argparse.ArgumentParser(
        prog="myclaw",
        description="🦞 MyClaw — 你的个人 AI 助手 (OpenClaw Python 版)",
    )
    parser.add_argument(
        "--config", "-c",
        help="配置文件路径 (默认: myclaw.json)",
        default=None,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # chat 命令
    chat_parser = subparsers.add_parser("chat", help="终端对话模式")
    chat_parser.add_argument("--new", action="store_true", help="清空历史，开始新对话")

    # run 命令
    subparsers.add_parser("run", help="启动 Gateway 服务")

    args = parser.parse_args()

    if args.command == "chat":
        cmd_chat(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

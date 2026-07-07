import os   
import sys 
import httpx
import json
import anthropic
from config import AgentConfig
from session import Session
from tools import tools


_SENSITIVE_HEADERS = {"authorization", "x-api-key", "api-key"}


async def _log_request(request):
    """拦截并打印 API 请求（对敏感信息脱敏）"""
    print("\n[API Request]")
    print(f"  URL: {request.method} {request.url}")

    # 打印脱敏后的请求头
    for name, value in request.headers.items():
        if name.lower() in _SENSITIVE_HEADERS:
            # 只显示最后 4 位
            masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "****"
            print(f"  Header {name}: {masked}")

    try:
        body = json.loads(request.content.decode())
        for key, value in body.items():
            if key == "messages":
                print(f"  {key}:")
                for i, msg in enumerate(value):
                    print(f"    [{i}] role={msg.get('role')}")
                    print(f"        content={json.dumps(msg.get('content'), ensure_ascii=False, indent=10)}")
            else:
                print(f"  {key}: {value}")
    except Exception:
        print(f"  Body: <decode failed>")

def _extract_text(content) -> str:
    """提取响应 content 中所有 text block 的文本（响应可能包含非 text 块，不能假设 content[0] 是文本）"""
    return "\n".join(
        block.text for block in content if getattr(block, "type", None) == "text"
    )


class Agent:
    """
    Agent模块
    """
    def __init__(self, config: AgentConfig):
        self.config = config
        self.client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url or None,
            http_client=httpx.AsyncClient(event_hooks={"request": [_log_request]}),
        )
        print(f"[agent] 初始化完成，模型: {config.model}")

    async def run(self, user_message: str, session: Session) -> str:
        """
        核心方法：处理一条用户消息，返回 AI 的回复。
        """
        # 1. 添加用户消息到 session
        session.add_message("user", user_message)

        # 2. 准备 API 调用参数
        messages = session.get_messages_for_api()

        # 3. 调用 Claude API
        MAX_TOOL_ROUNDS = 10
        try:
            for _round in range(MAX_TOOL_ROUNDS):
                response = await self.client.messages.create(
                    model=self.config.model,
                    max_tokens=4096,
                    system=self.config.system_prompt,
                    messages=messages,
                    tools=list(tools.get_tools_schema()),
                )
                messages.append({
                        "role": "assistant",
                        "content": response.content,
                    })
                if response.stop_reason == "end_turn":
                    break
                elif response.stop_reason == "tool_use":
                    tool_result = []
                    permission_denied = False
                    for block in response.content:
                        if block.type == "tool_use":
                            try:
                                result = tools.execute_tool(block.name, block.input)
                            except PermissionError as e:
                                result = f"[安全限制] {e}"
                                permission_denied = True
                            tool_result.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            })
                    messages.append({
                        "role": "user",
                        "content": tool_result,
                    })
                    if permission_denied:
                        #触发安全限制
                        response = await self.client.messages.create(
                            model=self.config.model,
                            max_tokens=1024,
                            system="你的工具调用触发了安全限制，被系统拦截。请停止调用工具，并告知用户：该操作因安全策略被拒绝。",
                            messages=messages,
                        )
                        reply = _extract_text(response.content) or "操作被安全限制拒绝。"
                        session.add_message("assistant", reply)
                        return reply
            # 正常结束（end_turn）
            if response.stop_reason == "end_turn":
                reply = _extract_text(response.content)
                session.add_message("assistant", reply)
                return reply

            # 循环次数耗尽，强制停止
            fallback = "抱歉，工具调用轮次已达上限，无法继续执行。请简化你的请求后重试。"
            session.add_message("assistant", fallback)
            return fallback

        except anthropic.APIError as e:
            error_msg = f"[agent] API 调用失败: {e}"
            print(error_msg)
            # 出错时移除刚添加的用户消息，保持 session 干净
            if session.messages and session.messages[-1].role == "user":
                session.messages.pop()
            return f"抱歉，AI 调用出错了: {e}"


            
if __name__ == "__main__":
    # 1. 创建配置（需要真实的 API Key）
      config = AgentConfig(
          model="claude-sonnet-4-20250514",
          api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
      )

      if not config.api_key:
          print("请设置环境变量 ANTHROPIC_API_KEY")
          sys.exit(1)

      # 2. 创建 Agent 和 Session
      agent = Agent(config)
      session = Session(session_key="test")

      # 3. 测试对话
      test_messages = [
          "你好,有什么工具可以使用？",
          "帮我解读一下/Users/liuxicheng/src/myclaw这个项目吧"
      ]

      async def _main():
          for msg in test_messages:
              resp = await agent.run(msg, session)
              print(f"\n[Response]\n\n")
              print(resp)

      import asyncio
      asyncio.run(_main())
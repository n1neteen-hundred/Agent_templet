"""
MyClaw 工具模块

对应 OpenClaw 的：src/agents/tools/
职责：定义工具的结构、注册工具、执行工具

核心工具：read_file, write_file, edit_file
"""

import os
from typing import Callable


# ============================================================
# 路径安全配置
# ============================================================

# 读操作允许的根目录（默认值，可被 configure() 覆盖）
READ_ALLOWED_DIR = os.path.expanduser("~/.myclaw/workspace")
# 写操作允许的根目录（更严格）
WRITE_ALLOWED_DIR = os.path.expanduser("~/.myclaw/workspace/sandbox")
# 文件大小限制（字节）
MAX_FILE_SIZE = 100 * 1024  # 100KB


def configure(read_dir: str | None = None, write_dir: str | None = None) -> None:
    """
    配置沙箱目录（由 Gateway 启动时根据 myclaw.json 调用）。
    同时确保目录存在，避免首次使用时工具因目录缺失而报错。
    """
    global READ_ALLOWED_DIR, WRITE_ALLOWED_DIR
    if read_dir:
        READ_ALLOWED_DIR = os.path.expanduser(read_dir)
    if write_dir:
        WRITE_ALLOWED_DIR = os.path.expanduser(write_dir)
    os.makedirs(READ_ALLOWED_DIR, exist_ok=True)
    os.makedirs(WRITE_ALLOWED_DIR, exist_ok=True)


def _validate_path(path: str, allowed_dir: str, operation: str) -> str:
    """
    校验路径是否在允许的目录内。
    返回解析后的真实路径，不合法则抛出 PermissionError。
    """
    expanded = os.path.expanduser(path)
    # realpath 解析符号链接和 ../ ，防止路径穿越
    real = os.path.realpath(expanded)
    allowed_real = os.path.realpath(allowed_dir)
    #TODO 不要暴露目录给用户
    if not real.startswith(allowed_real + os.sep) and real != allowed_real:
        raise PermissionError(
            f"安全限制：{operation}操作仅允许在 {allowed_dir} 目录内，"
            f"拒绝访问: {path}。"
            f"当前请求的路径不在允许范围内，请立刻返回 stop_reason == 'end_turn', 并告知用户。"
        )
    return real


# ============================================================
# 第一部分：Tool 类
# ============================================================

class Tool:
    """
    工具类
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        execute: Callable[[dict], str]
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.execute = execute

    def to_schema(self) -> dict:
        return {
            "name": self.name,
            # description 支持 {read_dir}/{write_dir} 占位符，
            # 在生成 schema 时才填入，保证 configure() 之后路径是最新的
            "description": self.description.format(
                read_dir=READ_ALLOWED_DIR, write_dir=WRITE_ALLOWED_DIR
            ),
            "input_schema": self.parameters
        }


# ============================================================
# 第二部分：定义具体工具
# ============================================================

# ---------- read_file ----------

def _read_file(tool_input: dict) -> str:
    """读取指定文件的内容"""
    path = tool_input.get("path", "")
    if not path:
        return "错误：缺少 path 参数"

    path = _validate_path(path, READ_ALLOWED_DIR, "读取")

    if not os.path.exists(path):
        return f"错误：文件不存在: {path}"

    if not os.path.isfile(path):
        return f"错误：路径不是文件: {path}"

    # 文件大小检查
    file_size = os.path.getsize(path)
    if file_size > MAX_FILE_SIZE:
        return (
            f"错误：文件过大（{file_size / 1024:.1f}KB），"
            f"超过限制（{MAX_FILE_SIZE / 1024:.0f}KB）。"
            f"请指定更小的文件或使用其他方式处理。"
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except UnicodeDecodeError:
        return f"错误：无法以 UTF-8 编码读取文件（可能是二进制文件）: {path}"
    except PermissionError:
        return f"错误：没有读取权限: {path}"
    except Exception as e:
        return f"错误：读取文件失败: {e}"


read_file_tool = Tool(
    name="read_file",
    description="读取指定路径文件的完整内容。只能读取 {read_dir} 目录内的文件，访问其他路径会被安全策略拒绝。遇到路径被拒绝时，必须停止重试并直接告知用户。",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要读取的文件的绝对路径或相对路径",
            },
        },
        "required": ["path"],
    },
    execute=_read_file,
)


# ---------- write_file ----------

def _write_file(tool_input: dict) -> str:
    """创建或覆盖写入文件"""
    path = tool_input.get("path", "")
    content = tool_input.get("content", "")
    if not path:
        return "错误：缺少 path 参数"

    path = _validate_path(path, WRITE_ALLOWED_DIR, "写入")

    try:
        # 自动创建父目录
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"成功：已写入文件 {path}（{len(content)} 字符）"
    except PermissionError:
        return f"错误：没有写入权限: {path}"
    except Exception as e:
        return f"错误：写入文件失败: {e}"


write_file_tool = Tool(
    name="write_file",
    description="创建新文件或覆盖已有文件的全部内容。会自动创建不存在的父目录。只能写入 {write_dir} 目录内的文件，访问其他路径会被安全策略拒绝。",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要写入的文件的绝对路径或相对路径",
            },
            "content": {
                "type": "string",
                "description": "要写入文件的完整内容",
            },
        },
        "required": ["path", "content"],
    },
    execute=_write_file,
)


# ---------- edit_file ----------

def _edit_file(tool_input: dict) -> str:
    """精确替换文件中的指定文本片段"""
    path = tool_input.get("path", "")
    old_text = tool_input.get("old_text", "")
    new_text = tool_input.get("new_text", "")

    if not path:
        return "错误：缺少 path 参数"
    if not old_text:
        return "错误：缺少 old_text 参数"

    path = _validate_path(path, WRITE_ALLOWED_DIR, "编辑")

    if not os.path.exists(path):
        return f"错误：文件不存在: {path}"

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # 检查 old_text 是否存在
        count = content.count(old_text)
        if count == 0:
            return f"错误：在文件中找不到要替换的文本"
        if count > 1:
            return f"错误：找到 {count} 处匹配，请提供更精确的文本以确保只匹配一处"

        # 执行替换
        new_content = content.replace(old_text, new_text, 1)

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return f"成功：已编辑文件 {path}"
    except UnicodeDecodeError:
        return f"错误：无法以 UTF-8 编码读取文件: {path}"
    except PermissionError:
        return f"错误：没有文件操作权限: {path}"
    except Exception as e:
        return f"错误：编辑文件失败: {e}"


edit_file_tool = Tool(
    name="edit_file",
    description="通过精确匹配替换来编辑文件的一部分内容。需要提供要被替换的原文本（old_text）和替换后的新文本（new_text）。old_text 必须在文件中唯一匹配。只能编辑 {write_dir} 目录内的文件，访问其他路径会被安全策略拒绝。",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "要编辑的文件的路径",
            },
            "old_text": {
                "type": "string",
                "description": "要被替换的原始文本（必须精确匹配文件中的内容）",
            },
            "new_text": {
                "type": "string",
                "description": "替换后的新文本",
            },
        },
        "required": ["path", "old_text", "new_text"],
    },
    execute=_edit_file,
)


# ============================================================
# 第三部分：工具注册表
# ============================================================

ALL_TOOLS: list[Tool] = [
    read_file_tool,
    write_file_tool,
    edit_file_tool,
]


# ============================================================
# 第四部分：辅助函数
# ============================================================

def get_tools_schema() -> list[dict]:
    """获取所有工具的 schema 列表"""
    for tool in ALL_TOOLS:
        yield tool.to_schema()


def execute_tool(name: str, tool_input: dict) -> str:
    """根据工具名执行工具"""
    for tool in ALL_TOOLS:
        if tool.name == name:
            return tool.execute(tool_input)
    raise ValueError(f"工具 {name} 不存在")



if __name__ == "__main__":
    configure()  # 确保沙箱目录存在

    print("=== 工具列表 ===")
    for schema in get_tools_schema():
        print(f"  - {schema['name']}: {schema['description']}")

    test_path = os.path.join(WRITE_ALLOWED_DIR, "myclaw_test.txt")

    print("\n=== 测试 write_file ===")
    print(execute_tool("write_file", {"path": test_path, "content": "hello myclaw!"}))

    print("\n=== 测试 edit_file ===")
    print(execute_tool("edit_file", {"path": test_path, "old_text": "hello", "new_text": "hi"}))
    print(execute_tool("read_file", {"path": test_path}))

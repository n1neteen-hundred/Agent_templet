"""
MyClaw WeChat Channel — 通过微信 ClawBot ilink API 收发消息

基于腾讯官方 @tencent-weixin/openclaw-weixin 插件的 API 规范实现。
认证流程：扫码登录 → 获取 bot_token → 长轮询收消息 → 调用 API 发消息
"""

import asyncio
import json
import os
import struct
import time
import uuid
from base64 import b64encode
from pathlib import Path

import httpx

from channels import BaseChannel

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
ILINK_APP_ID = "bot"
CHANNEL_VERSION = "2.1.1"  # 与官方插件版本对齐
ILINK_APP_CLIENT_VERSION = (2 << 16) | (1 << 8) | 1  # 0x00020101

LONG_POLL_TIMEOUT_S = 35
API_TIMEOUT_S = 15
QR_POLL_TIMEOUT_S = 35
QR_FETCH_TIMEOUT_S = 5

MAX_CONSECUTIVE_FAILURES = 3
BACKOFF_DELAY_S = 30
RETRY_DELAY_S = 2
MAX_QR_REFRESH = 3

# 消息类型
MSG_TYPE_BOT = 2
MSG_ITEM_TEXT = 1
MSG_STATE_FINISH = 2


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _random_wechat_uin() -> str:
    """生成随机 X-WECHAT-UIN header（与官方实现一致）"""
    uint32 = struct.unpack(">I", os.urandom(4))[0]
    return b64encode(str(uint32).encode()).decode()


def _generate_client_id() -> str:
    return f"myclaw-weixin-{uuid.uuid4().hex[:12]}"


def _common_headers() -> dict[str, str]:
    return {
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
    }


def _post_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _random_wechat_uin(),
        **_common_headers(),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _base_info() -> dict:
    return {"channel_version": CHANNEL_VERSION}


def _extract_text(item_list: list[dict] | None) -> str:
    """从 item_list 中提取文本内容"""
    if not item_list:
        return ""
    for item in item_list:
        if item.get("type") == MSG_ITEM_TEXT:
            text_item = item.get("text_item", {})
            text = text_item.get("text", "")
            ref = item.get("ref_msg")
            if not ref:
                return text
            # 引用消息：拼接引用内容
            parts = []
            if ref.get("title"):
                parts.append(ref["title"])
            ref_item = ref.get("message_item")
            if ref_item:
                ref_text = _extract_text([ref_item])
                if ref_text:
                    parts.append(ref_text)
            if parts:
                return f"[引用: {' | '.join(parts)}]\n{text}"
            return text
        # 语音转文字
        if item.get("type") == 3:  # VOICE
            voice = item.get("voice_item", {})
            if voice.get("text"):
                return voice["text"]
    return ""


# ---------------------------------------------------------------------------
# 凭证持久化
# ---------------------------------------------------------------------------

class WeChatCredentialStore:
    """管理 WeChat 账号凭证、sync buf 和 context token 的持久化"""

    def __init__(self, store_dir: str):
        self.store_dir = Path(store_dir).expanduser()
        self.store_dir.mkdir(parents=True, exist_ok=True)
        # 内存缓存 context_token: {user_id: token}
        self._context_tokens: dict[str, str] = {}

    def _account_path(self, account_id: str) -> Path:
        return self.store_dir / f"{account_id}.json"

    def _sync_path(self, account_id: str) -> Path:
        return self.store_dir / f"{account_id}.sync.json"

    def _context_tokens_path(self, account_id: str) -> Path:
        return self.store_dir / f"{account_id}.context-tokens.json"

    def save_account(self, account_id: str, token: str, base_url: str, user_id: str = "") -> None:
        data = {
            "token": token,
            "base_url": base_url,
            "user_id": user_id,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        path = self._account_path(account_id)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)

    def load_account(self, account_id: str) -> dict | None:
        path = self._account_path(account_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def save_sync_buf(self, account_id: str, buf: str) -> None:
        self._sync_path(account_id).write_text(
            json.dumps({"get_updates_buf": buf}), encoding="utf-8"
        )

    def load_sync_buf(self, account_id: str) -> str:
        path = self._sync_path(account_id)
        if not path.exists():
            return ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("get_updates_buf", "")
        except (json.JSONDecodeError, OSError):
            return ""

    def set_context_token(self, account_id: str, user_id: str, token: str) -> None:
        self._context_tokens[user_id] = token
        self._persist_context_tokens(account_id)

    def get_context_token(self, user_id: str) -> str | None:
        return self._context_tokens.get(user_id)

    def restore_context_tokens(self, account_id: str) -> None:
        path = self._context_tokens_path(account_id)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for uid, tok in data.items():
                if isinstance(tok, str) and tok:
                    self._context_tokens[uid] = tok
        except (json.JSONDecodeError, OSError):
            pass

    def _persist_context_tokens(self, account_id: str) -> None:
        path = self._context_tokens_path(account_id)
        path.write_text(json.dumps(self._context_tokens), encoding="utf-8")


# ---------------------------------------------------------------------------
# WeChat Channel
# ---------------------------------------------------------------------------

class WeChatChannel(BaseChannel):

    def __init__(self, config):
        super().__init__(name="wechat")
        self.base_url: str = getattr(config, "base_url", DEFAULT_BASE_URL)
        self.store = WeChatCredentialStore(
            getattr(config, "token_path", "~/.myclaw/wechat")
        )
        self.token: str | None = None
        self.account_id: str | None = None
        self.get_updates_buf: str = ""
        self._poll_task: asyncio.Task | None = None
        self._running = False
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(LONG_POLL_TIMEOUT_S + 10))
        self._running = True

        # 尝试加载已有凭证
        loaded = self._try_load_existing_account()
        if not loaded:
            await self._qr_login()

        # 恢复 sync buf 和 context tokens
        if self.account_id:
            self.get_updates_buf = self.store.load_sync_buf(self.account_id)
            self.store.restore_context_tokens(self.account_id)
            if self.get_updates_buf:
                print(f"[wechat] 恢复上次同步状态 ({len(self.get_updates_buf)} bytes)")

        print(f"[wechat] 启动消息轮询 (account={self.account_id})")
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
        print("[wechat] 已停止")

    async def send_message(self, recipient: str, text: str) -> None:
        context_token = self.store.get_context_token(recipient)
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": recipient,
                "client_id": _generate_client_id(),
                "message_type": MSG_TYPE_BOT,
                "message_state": MSG_STATE_FINISH,
                "item_list": [
                    {"type": MSG_ITEM_TEXT, "text_item": {"text": text}}
                ],
            },
            "base_info": _base_info(),
        }
        if context_token:
            body["msg"]["context_token"] = context_token

        await self._api_post("ilink/bot/sendmessage", body)

    # ------------------------------------------------------------------
    # 凭证加载
    # ------------------------------------------------------------------

    def _try_load_existing_account(self) -> bool:
        """尝试加载已保存的账号，遍历 store_dir 中的 .json 文件"""
        for p in self.store.store_dir.glob("*.json"):
            if p.name.endswith((".sync.json", ".context-tokens.json")):
                continue
            account_id = p.stem
            data = self.store.load_account(account_id)
            if data and data.get("token"):
                self.token = data["token"]
                self.account_id = account_id
                self.base_url = data.get("base_url") or self.base_url
                print(f"[wechat] 已加载凭证 account={account_id}")
                return True
        return False

    # ------------------------------------------------------------------
    # QR 登录
    # ------------------------------------------------------------------

    async def _qr_login(self) -> None:
        print("[wechat] 开始扫码登录...")
        qr_base_url = DEFAULT_BASE_URL
        qrcode_value, qrcode_url = await self._fetch_qrcode(qr_base_url)

        # 在终端显示二维码
        self._print_qrcode(qrcode_url)

        # 轮询等待扫码
        current_base_url = qr_base_url
        scanned_printed = False
        refresh_count = 1

        deadline = time.time() + 480  # 8 分钟超时
        while time.time() < deadline:
            status_resp = await self._poll_qr_status(current_base_url, qrcode_value)
            status = status_resp.get("status", "wait")

            if status == "wait":
                pass
            elif status == "scaned":
                if not scanned_printed:
                    print("\n[wechat] 👀 已扫码，请在微信中确认...")
                    scanned_printed = True
            elif status == "expired":
                refresh_count += 1
                if refresh_count > MAX_QR_REFRESH:
                    raise RuntimeError("二维码多次过期，登录失败")
                print(f"\n[wechat] 二维码已过期，正在刷新 ({refresh_count}/{MAX_QR_REFRESH})...")
                qrcode_value, qrcode_url = await self._fetch_qrcode(qr_base_url)
                self._print_qrcode(qrcode_url)
                scanned_printed = False
            elif status == "scaned_but_redirect":
                redirect_host = status_resp.get("redirect_host")
                if redirect_host:
                    current_base_url = f"https://{redirect_host}"
                    print(f"[wechat] IDC 重定向 → {redirect_host}")
            elif status == "confirmed":
                bot_token = status_resp.get("bot_token")
                bot_id = status_resp.get("ilink_bot_id")
                base_url = status_resp.get("baseurl")
                user_id = status_resp.get("ilink_user_id", "")

                if not bot_id:
                    raise RuntimeError("登录失败：服务器未返回 ilink_bot_id")

                self.token = bot_token
                self.account_id = bot_id
                if base_url:
                    self.base_url = base_url

                # 持久化凭证
                self.store.save_account(bot_id, bot_token, self.base_url, user_id)
                print(f"\n[wechat] ✅ 登录成功！account={bot_id}")
                return

            await asyncio.sleep(1)

        raise RuntimeError("登录超时")

    async def _fetch_qrcode(self, base_url: str) -> tuple[str, str]:
        """获取二维码，返回 (qrcode_value, qrcode_img_url)"""
        url = f"{base_url}/ilink/bot/get_bot_qrcode?bot_type=3"
        resp = await self._client.get(
            url, headers=_common_headers(), timeout=QR_FETCH_TIMEOUT_S
        )
        resp.raise_for_status()
        data = resp.json()
        return data["qrcode"], data["qrcode_img_content"]

    async def _poll_qr_status(self, base_url: str, qrcode: str) -> dict:
        """长轮询二维码扫描状态"""
        url = f"{base_url}/ilink/bot/get_qrcode_status?qrcode={qrcode}"
        try:
            resp = await self._client.get(
                url, headers=_common_headers(), timeout=QR_POLL_TIMEOUT_S
            )
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.HTTPStatusError):
            return {"status": "wait"}

    def _print_qrcode(self, url: str) -> None:
        """在终端打印二维码"""
        try:
            import qrcode as qr_lib
            qr = qr_lib.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except ImportError:
            pass
        print(f"\n如果二维码无法显示，请用浏览器打开以下链接扫码：\n{url}\n")

    # ------------------------------------------------------------------
    # 消息轮询
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        consecutive_failures = 0
        next_timeout = LONG_POLL_TIMEOUT_S

        while self._running:
            try:
                resp = await self._get_updates(next_timeout)

                # 更新服务端建议的超时时间
                server_timeout = resp.get("longpolling_timeout_ms")
                if server_timeout and server_timeout > 0:
                    next_timeout = server_timeout / 1000

                # 检查 API 错误
                ret = resp.get("ret", 0)
                errcode = resp.get("errcode", 0)
                if ret != 0 or errcode != 0:
                    # session 过期 (errcode -14)
                    if errcode == -14 or ret == -14:
                        print("[wechat] session 过期，需要重新登录")
                        self._running = False
                        break

                    consecutive_failures += 1
                    print(f"[wechat] getUpdates 失败: ret={ret} errcode={errcode} "
                          f"({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES})")
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        consecutive_failures = 0
                        await asyncio.sleep(BACKOFF_DELAY_S)
                    else:
                        await asyncio.sleep(RETRY_DELAY_S)
                    continue

                consecutive_failures = 0

                # 保存 sync buf
                new_buf = resp.get("get_updates_buf", "")
                if new_buf:
                    self.get_updates_buf = new_buf
                    if self.account_id:
                        self.store.save_sync_buf(self.account_id, new_buf)

                # 处理消息
                msgs = resp.get("msgs", [])
                for msg in msgs:
                    await self._handle_inbound_message(msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                print(f"[wechat] 轮询错误 ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {e}")
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    consecutive_failures = 0
                    await asyncio.sleep(BACKOFF_DELAY_S)
                else:
                    await asyncio.sleep(RETRY_DELAY_S)

    async def _get_updates(self, timeout_s: float) -> dict:
        body = {
            "get_updates_buf": self.get_updates_buf,
            "base_info": _base_info(),
        }
        try:
            return await self._api_post(
                "ilink/bot/getupdates", body, timeout_s=timeout_s
            )
        except httpx.TimeoutException:
            # 长轮询超时是正常的
            return {"ret": 0, "msgs": [], "get_updates_buf": self.get_updates_buf}

    async def _handle_inbound_message(self, msg: dict) -> None:
        """处理一条收到的消息"""
        from_user = msg.get("from_user_id", "")
        if not from_user:
            return

        # 只处理用户消息 (message_type=1)
        if msg.get("message_type") != 1:
            return

        # 保存 context_token
        context_token = msg.get("context_token")
        if context_token and self.account_id:
            self.store.set_context_token(self.account_id, from_user, context_token)

        # 提取文本
        text = _extract_text(msg.get("item_list"))
        if not text:
            return

        print(f"[wechat] 收到消息 from={from_user}: {text[:50]}...")

        # 交给 gateway 处理
        if self._message_handler:
            try:
                reply = await self._message_handler("wechat", from_user, text)
                if reply:
                    await self.send_message(from_user, reply)
            except Exception as e:
                print(f"[wechat] 处理消息失败: {e}")
                try:
                    await self.send_message(from_user, f"⚠️ 处理消息时出错：{e}")
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # HTTP 请求
    # ------------------------------------------------------------------

    async def _api_post(self, endpoint: str, body: dict, timeout_s: float = API_TIMEOUT_S) -> dict:
        url = f"{self.base_url.rstrip('/')}/{endpoint}"
        headers = _post_headers(self.token)
        resp = await self._client.post(
            url, json=body, headers=headers, timeout=timeout_s
        )
        resp.raise_for_status()
        return resp.json()

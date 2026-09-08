import asyncio
import ssl
import json
import logging
import platform
from urllib.parse import urlparse
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# 导入配置
from ..config import DEFAULT_API_KEY, DEFAULT_BASE_URL

# 阿里云百炼/DashScope 稳定公网 IP 节点（仅在 macOS 代理穿透时备用）
DASHSCOPE_IPS = [
    "8.140.217.18",
    "39.96.198.249",
    "39.96.213.166",
    "8.152.159.24",
]


def _get_physical_local_ip_macos() -> Optional[str]:
    """
    仅在 macOS 环境下，通过 ifconfig 获取物理网卡真实 IP，
    用于绑定 socket 连接以绕过 TUN/全局代理干扰。
    Linux/云端环境不需要此函数。
    """
    import subprocess
    import re
    for iface in ["en0", "en1", "en2"]:
        try:
            out = subprocess.check_output(["ifconfig", iface], text=True, stderr=subprocess.DEVNULL)
            m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", out)
            if m and not m.group(1).startswith("127."):
                return m.group(1)
        except Exception:
            continue
    return None


async def _httpx_post_chat(url: str, api_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    使用 httpx 标准异步 HTTP 客户端发送请求（适用于所有平台，包括 Linux/Render 云端）。
    超时设置：连接 15 秒，读取 120 秒（大文档多模态翻译需要更长时间）。
    """
    import httpx
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _socket_post_chat_macos(
    host: str,
    port: int,
    path: str,
    api_key: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    仅 macOS 使用的底层 SSL Socket 直连方案，用于绕过 Clash/TUN 代理干扰。
    在 Linux/Render 云端不调用此方法。
    """
    ctx = ssl.create_default_context()
    local_ip = _get_physical_local_ip_macos()
    local_addr = (local_ip, 0) if local_ip else None

    for ip in DASHSCOPE_IPS:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    ip, port, ssl=ctx, server_hostname=host, local_addr=local_addr
                ),
                timeout=15.0,
            )
            body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = (
                f"POST {path} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                f"Authorization: Bearer {api_key}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("utf-8") + body_bytes

            writer.write(req)
            await writer.drain()
            resp_bytes = await asyncio.wait_for(reader.read(), timeout=120.0)
            writer.close()
            await writer.wait_closed()

            resp_str = resp_bytes.decode("utf-8", errors="ignore")
            parts = resp_str.split("\r\n\r\n", 1)
            if len(parts) < 2:
                raise RuntimeError("服务器响应格式异常")

            header_str, body_str = parts
            status_line = header_str.split("\r\n")[0]
            status_code = int(status_line.split()[1])

            # 处理 Chunked 传输编码
            if "transfer-encoding: chunked" in header_str.lower():
                clean_body = ""
                chunk_stream = body_str
                while chunk_stream:
                    lines = chunk_stream.split("\r\n", 1)
                    chunk_size_str = lines[0].strip()
                    if not chunk_size_str:
                        break
                    try:
                        chunk_size = int(chunk_size_str, 16)
                    except ValueError:
                        break
                    if chunk_size == 0:
                        break
                    chunk_content = lines[1][:chunk_size]
                    clean_body += chunk_content
                    chunk_stream = lines[1][chunk_size + 2:]
                body_str = clean_body

            data = json.loads(body_str.strip())
            if status_code != 200:
                err_msg = data.get("error", {}).get("message") or body_str
                raise RuntimeError(f"HTTP {status_code}: {err_msg}")
            return data

        except Exception as e:
            logger.warning(f"Socket 直连 IP {ip} 失败: {e}")
            continue

    raise RuntimeError("Socket 直连所有节点均失败")


class QwenClient:
    """
    通义千问 / DashScope API 客户端
    - 主路：使用 httpx 标准异步 HTTP 客户端（兼容 Linux/Render 云端）
    - 备路（仅 macOS）：若 httpx 失败，尝试 SSL Socket 直连以绕过本地代理干扰
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        初始化通义千问客户端
        :param api_key: 用户传入的 API Key，未传则使用环境变量或默认配置
        :param base_url: DashScope 接口基础 URL
        """
        self.api_key = api_key or DEFAULT_API_KEY
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._is_macos = platform.system() == "Darwin"

    def get_system_prompt(self, mode: str = "courseware") -> str:
        """
        获取不同场景下的专业翻译 System Prompt
        :param mode: 翻译模式 'courseware'(课件) / 'academic'(论文) / 'general'(通用)
        """
        if mode == "courseware":
            return (
                "你是一个顶级的双语课件与教学幻灯片翻译引擎。请将用户提供的课件内容翻译为中文。\n"
                "翻译准则：\n"
                "1. 保持原文的排版结构、标题层级与项目符号（列表序号如 1. 2. 或 - 等）；\n"
                "2. 语言简明扼要、表达生动，符合大学专业教学幻灯片风格；\n"
                "3. 遇到代码、变量名、LaTeX 数学公式（如 $...$ 或 $$...$$）必须原样保留，切勿破坏；\n"
                "4. 专有名词若无公认中译，可在中文后用括号保留英文；\n"
                "5. 只输出翻译后的内容，不要输出任何引言、解释或多余的寒暄语。"
            )
        elif mode == "academic":
            return (
                "你是一个资深的学术论文翻译专家。请将用户提供的论文内容翻译为地道严谨的中文。\n"
                "翻译准则：\n"
                "1. 文风严肃、规范，符合中文顶会顶刊的学术规范；\n"
                "2. 必须绝对保留所有的 LaTeX 公式（$...$、$$...$$）、公式符号与上下标；\n"
                "3. 保留文献引用标记（如 [1], [2-4]）及图表标识（如 Figure 1, Table 2）；\n"
                "4. 准确翻译领域专业术语，保证全文术语一致性；\n"
                "5. 只输出翻译结果，切勿添加任何提示、多余标记或寒暄。"
            )
        else:
            return (
                "你是一个高精度的双语翻译引擎。请将用户输入的英文内容准确翻译为地道通顺的中文，"
                "保留原有的格式、换行、数字与公式，直接输出翻译结果。"
            )

    async def _raw_post_chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        发送聊天请求，优先使用 httpx（适配所有平台），在 macOS 上失败时才回退到 Socket 直连。
        """
        url = f"{self.base_url}/chat/completions"

        # 主路：httpx（Linux/Render 云端唯一可用方案，macOS 也首选）
        try:
            return await _httpx_post_chat(url, self.api_key, payload)
        except Exception as e:
            logger.warning(f"httpx 请求失败: {e}")
            # 仅在 macOS 上尝试 Socket 直连（用于绕过本地 Clash/TUN 代理）
            if self._is_macos:
                logger.info("正在尝试 macOS Socket 直连备用方案...")
                parsed = urlparse(self.base_url)
                host = parsed.hostname or "dashscope.aliyuncs.com"
                port = parsed.port or 443
                path = parsed.path.rstrip("/") + "/chat/completions"
                return await _socket_post_chat_macos(host, port, path, self.api_key, payload)
            raise

    async def translate_text(
        self,
        text: str,
        model: str = "qwen3.8-flash",
        mode: str = "courseware",
        temperature: float = 0.2,
    ) -> str:
        """
        调用通义千问进行文本翻译
        :param text: 待翻译的原文
        :param model: 使用的模型名称
        :param mode: 翻译模式
        :param temperature: 采样温度（默认 0.2 以保障翻译稳定性）
        :return: 翻译后的中文文本
        """
        if not text.strip():
            return ""

        system_prompt = self.get_system_prompt(mode)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请翻译以下文本：\n\n{text}"},
            ],
            "temperature": temperature,
        }

        last_err = None
        for attempt in range(3):
            try:
                data = await self._raw_post_chat(payload)
                choice = data["choices"][0]
                content = choice["message"].get("content", "")
                # 兼容思考模型（有 reasoning_content 但 content 为空）
                if not content and "reasoning_content" in choice["message"]:
                    content = choice["message"]["reasoning_content"]
                return content.strip()
            except Exception as e:
                logger.warning(f"调用模型 {model} 第 {attempt + 1} 次重试: {e}")
                last_err = e
                await asyncio.sleep(1.5)

        raise RuntimeError(f"翻译失败，已重试 3 次: {last_err}")

    async def test_connection(self, model: str = "qwen3.8-flash") -> Dict[str, Any]:
        """
        测试 API Key 与网络连通性
        """
        try:
            res = await self.translate_text(
                text="Hello, this is an API connection test.",
                model=model,
                mode="general",
            )
            return {"success": True, "reply": res}
        except Exception as e:
            return {"success": False, "error": str(e)}

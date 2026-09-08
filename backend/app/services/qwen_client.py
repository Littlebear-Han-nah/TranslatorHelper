import asyncio
import ssl
import json
import socket
import logging
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any
from ..config import DEFAULT_API_KEY, DEFAULT_BASE_URL

logger = logging.getLogger(__name__)

# 阿里云百炼/DashScope 真实稳定公网 IP 节点列表（保障在各类代理/TUN环境下均能直连）
DASHSCOPE_IPS = [
    "8.140.217.18",
    "39.96.198.249",
    "39.96.213.166",
    "8.152.159.24"
]

def get_physical_local_ip() -> Optional[str]:
    """
    通过 macOS 系统的 ifconfig 获取物理无线/有线网卡真实 IP（如 en0/en1），
    用于直接绑定 socket 发起连接，彻底避开 TUN/全局代理虚拟网卡的干扰。
    """
    import subprocess
    import re
    for iface in ["en0", "en1", "en2", "eth0"]:
        try:
            out = subprocess.check_output(["ifconfig", iface], text=True, stderr=subprocess.DEVNULL)
            m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", out)
            if m and not m.group(1).startswith("127."):
                return m.group(1)
        except Exception:
            continue
    return None

class QwenClient:
    """
    通义千问 / DashScope 高性能 API 客户端
    具备抗代理与 TUN 干扰的自适应直连能力，专门针对学术论文、课件翻译进行模型提示词调优。
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        初始化通义千问客户端
        :param api_key: 用户传入的 API Key，若未传入则使用配置文件默认值
        :param base_url: 接口基础 URL，默认为 DashScope 兼容接口
        """
        self.api_key = api_key or DEFAULT_API_KEY
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    def get_system_prompt(self, mode: str = "courseware") -> str:
        """
        获取不同场景下的专业翻译 System Prompt
        :param mode: 'courseware' (课件模式), 'academic' (学术论文模式), 'general' (通用模式)
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
                "1. 文风严肃、规范、符合中文顶会顶刊（如 IEEE, ACM, Nature, Science）的学术规范；\n"
                "2. 必须绝对保留所有的 LaTeX 公式（包括内联 $...$ 和块级 $$...$$）、公式符号与上下标；\n"
                "3. 保留文献引用标记（如 [1], [2-4], Smith et al.）及图表标识（如 Figure 1, Table 2）；\n"
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
        通过底层高可靠异步 Socket 连接发起 HTTP/1.1 POST 请求，
        自动解析公网真实 IP 并绑定本地物理网卡，彻底规避代理软件/TUN拦截导致的 EOF 错误。
        """
        parsed = urlparse(self.base_url)
        host = parsed.hostname or "dashscope.aliyuncs.com"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path.rstrip("/") + "/chat/completions"

        target_ips = DASHSCOPE_IPS if host == "dashscope.aliyuncs.com" else [host]
        local_ip = get_physical_local_ip()
        ctx = ssl.create_default_context()

        last_error = None
        for ip in target_ips:
            try:
                # 尝试直连通信
                local_addr = (local_ip, 0) if local_ip else None
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        ip,
                        port,
                        ssl=ctx,
                        server_hostname=host,
                        local_addr=local_addr
                    ),
                    timeout=10.0
                )

                body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                req = (
                    f"POST {path} HTTP/1.1\r\n"
                    f"Host: {host}\r\n"
                    f"Authorization: Bearer {self.api_key}\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(body_bytes)}\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode("utf-8") + body_bytes

                writer.write(req)
                await writer.drain()

                # 读取服务端响应
                resp_bytes = await asyncio.wait_for(reader.read(), timeout=60.0)
                writer.close()
                await writer.wait_closed()

                resp_str = resp_bytes.decode("utf-8", errors="ignore")
                parts = resp_str.split("\r\n\r\n", 1)
                if len(parts) < 2:
                    raise RuntimeError("服务器响应格式异常")

                header_str, body_str = parts
                status_line = header_str.split("\r\n")[0]
                status_code = int(status_line.split()[1])

                # 处理 Chunked 传输编码（若存在）
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
                logger.warning(f"尝试 IP {ip} 失败: {e}，正在尝试备用节点...")
                last_error = e

        raise RuntimeError(f"调用 DashScope API 失败: {last_error}")

    async def translate_text(
        self,
        text: str,
        model: str = "qwen3.8-flash",
        mode: str = "courseware",
        temperature: float = 0.2,
    ) -> str:
        """
        异步调用通义千问进行文本翻译
        :param text: 待翻译的原文
        :param model: 调用的模型名称（如 qwen3.8-flash, qwen3.8-max 等）
        :param mode: 翻译模式（'courseware' 或 'academic'）
        :param temperature: 采样温度（默认 0.2 保障学术/课件翻译稳定性）
        :return: 翻译后的中文文本
        """
        if not text.strip():
            return ""

        system_prompt = self.get_system_prompt(mode)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请翻译以下文本：\n\n{text}"}
            ],
            "temperature": temperature,
        }

        # 自动重试 3 次
        last_err = None
        for attempt in range(3):
            try:
                data = await self._raw_post_chat(payload)
                choice = data["choices"][0]
                content = choice["message"].get("content", "")
                
                # 思考模型兼容处理
                if not content and "reasoning_content" in choice["message"]:
                    content = choice["message"]["reasoning_content"]

                return content.strip()
            except Exception as e:
                logger.warning(f"调用模型 {model} 重试第 {attempt+1} 次: {e}")
                last_err = e
                await asyncio.sleep(1.0)

        raise RuntimeError(f"翻译失败，已重试3次: {last_err}")

    async def test_connection(self, model: str = "qwen3.8-flash") -> Dict[str, Any]:
        """
        测试 API Key 与服务连通性
        """
        try:
            res = await self.translate_text(
                text="Hello, this is an API connection test.",
                model=model,
                mode="general"
            )
            return {"success": True, "reply": res}
        except Exception as e:
            return {"success": False, "error": str(e)}

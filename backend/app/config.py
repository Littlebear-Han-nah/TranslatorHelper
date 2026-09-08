import os
from pathlib import Path

# 项目根目录路径与存储路径
BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

# 确保目录存在
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 默认通义千问 API 配置（用户可通过前端界面随时覆盖或修改）
DEFAULT_API_KEY = os.getenv(
    "DASHSCOPE_API_KEY",
    "sk-ws-H.PDDLLRH.BX6X.MEYCIQC44Nz2sYrwmcqIXL_2A0F4qNyajfPZ6R6_un8C3ELvLAIhAPIZX7JmML8t_m1rRe1U72JV2dAtfsaE6bRiCT6tNzUq"
)
DEFAULT_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 支持的模型清单（用户可自由选择）
SUPPORTED_MODELS = [
    {"id": "qwen3.8-flash", "name": "通义千问 3.8 Flash (推荐/快速)", "tag": "快速高质"},
    {"id": "qwen3.8-max", "name": "通义千问 3.8 Max (学术深度精翻)", "tag": "最高质量"},
    {"id": "qwen3.8-max-0902", "name": "通义千问 3.8 Max (0902 版)", "tag": "深度学术"},
    {"id": "qwen3.8-27b", "name": "通义千问 3.8 27B", "tag": "平衡型"},
    {"id": "qwen3.7-flash", "name": "通义千问 3.7 Flash", "tag": "轻量"},
    {"id": "qwen3.7-flash-2026-07-15", "name": "通义千问 3.7 Flash (07-15)", "tag": "稳定"},
    {"id": "qwen3.7-max-2026-06-08", "name": "通义千问 3.7 Max (06-08)", "tag": "高精"},
    {"id": "qwen3.8-2.4t-a95b", "name": "通义千问 3.8 2.4T (A95B)", "tag": "长文本"},
    {"id": "qwen3.5-ocr", "name": "通义千问 3.5 OCR (图片/扫描件专用)", "tag": "视觉识别"},
    {"id": "deepseek-v4-flash-0731", "name": "DeepSeek V4 Flash (0731)", "tag": "极速"},
    {"id": "deepseek-v4-pro-0813", "name": "DeepSeek V4 Pro (0813)", "tag": "强逻辑"},
    {"id": "kimi-k3", "name": "Kimi K3 (长文档理解)", "tag": "长文"},
    {"id": "kimi-k2.7-code", "name": "Kimi K2.7 Code (技术代码)", "tag": "代码强化"},
    {"id": "glm-5.2", "name": "GLM 5.2 (智谱旗舰)", "tag": "综合强"},
]

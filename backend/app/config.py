"""Server-only configuration. Never expose credentials in API responses."""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / '.env')
DATA_DIR = Path(os.getenv('DATA_DIR', str(BASE_DIR / 'data')))
UPLOAD_DIR = DATA_DIR / 'uploads'
OUTPUT_DIR = DATA_DIR / 'outputs'
for directory in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR):
    directory.mkdir(parents=True, exist_ok=True)
DEFAULT_API_KEY = os.getenv('DASHSCOPE_API_KEY', '')
DEFAULT_BASE_URL = os.getenv('DASHSCOPE_BASE_URL', 'https://ws-z35kkg3gacz2xk3g.cn-beijing.maas.aliyuncs.com/compatible-mode/v1')
DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'qwen3.7-flash')
APP_ACCESS_TOKEN = os.getenv('APP_ACCESS_TOKEN', '')
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_PAGES = int(os.getenv('MAX_PAGES', '200'))
_models = [('Qwen', 'qwen3.8-27b'), ('Qwen', 'qwen3.7-flash-2026-07-15'), ('Qwen', 'qwen3.8-max-0902'), ('Qwen', 'qwen3.7-flash'), ('Kimi', 'kimi-k3'), ('DeepSeek', 'deepseek-v4-flash-0731'), ('DeepSeek', 'deepseek-v4-pro-0813'), ('GLM', 'glm-5.2')]
SUPPORTED_MODELS = json.loads(os.environ['MODEL_CATALOG_JSON']) if os.getenv('MODEL_CATALOG_JSON') else [{'id': m, 'name': m, 'provider': p} for p, m in _models]

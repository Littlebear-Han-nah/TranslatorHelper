#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
export PORT=8010
if /usr/bin/curl --silent --fail --max-time 2 "http://127.0.0.1:${PORT}/api/health" >/dev/null; then
  open "http://127.0.0.1:${PORT}"
  exit 0
fi
echo '翻译网站：http://127.0.0.1:8010'
echo '运行期间请保留此窗口。按 Control+C 停止服务。'
echo '在浏览器打开上面的地址，使用原有平台访问口令登录。'
exec bash run.sh

# Render 部署新版

新版保留原有 React + Python 架构。上传解析、OCR 和 Office 转换需要 Tesseract、LibreOffice 及磁盘，不能仅部署前端静态文件。

## 新服务部署

1. 将新版分支合并到 GitHub 的 `main`（或在 Blueprint 中修改 `branch` 为要验证的分支）。
2. 在 Render 新建 Blueprint，连接 `Littlebear-Han-nah/TranslatorHelper`，读取仓库中的 `render.yaml`。
3. 检查新服务名称 `translatorhelper-v2`、付费实例规格和 5 GB 持久磁盘。蓝图使用有足够内存运行 LibreOffice 的实例；创建前以 Render 确认页面显示的价格为准。
4. 在 Render 的秘密环境变量 `DASHSCOPE_API_KEY` 填入当前有效的千炼密钥。蓝图不包含任何密钥值。
5. `APP_ACCESS_TOKEN` 会生成独立的平台访问口令。部署后打开网站，在“模型设置”输入这个口令，再测试所选模型连接。
6. 等 `/api/health` 返回 `{"status":"ok","version":"2.0.0"}` 后，上传合成 PDF、PNG、DOCX、PPTX、XLSX 各一份验收。

`autoDeploy` 默认关闭。建议先用新服务验收实际复杂文档，再决定是否替换旧服务域名。

## 复用现有服务

保留 Docker 部署方式，在服务环境变量中更新 `DASHSCOPE_BASE_URL` 为你的专属兼容地址，设置 `DASHSCOPE_API_KEY` 和 `APP_ACCESS_TOKEN`，添加 `/app/data` 持久磁盘，并使用新版提交手动部署。旧版硬编码的密钥曾存在于仓库历史中，应在服务商控制台撤销旧密钥。

不要把 `.env`、API Key 或平台口令放入仓库、前端代码、Docker 构建参数或 PR 描述。Docker 构建只需要公共软件依赖。

## 运行边界

- SQLite + 本地文件用于单实例部署：必须保持 `--workers 1`，不要横向扩容多个副本共享这份数据库。
- 没有持久磁盘时，重新部署会丢失文件与任务记录。
- 有限并发用于控制 OCR / LibreOffice 内存占用；大文件仍可能需要提高实例内存。
- 免费实例不适合作为此配置的长期文档处理服务。蓝图含付费服务和磁盘，不会由本地构建自动创建或扣费。
- 容器以非 root 用户运行；仅 `/app/data` 保存上传、预览、PDF 与 SQLite。Office 临时目录随转换结束清理。
- 当前不提供自动清理、账户恢复或跨设备同步。定期备份并根据自己的保留策略清理 `/app/data`。

## 本地容器验证

```bash
docker build -t translatorhelper:v2 .
docker run --rm -p 8010:8000 --env-file .env -e DATA_DIR=/app/data -v translator-data:/app/data translatorhelper:v2
```

然后打开 http://127.0.0.1:8010 。本地源码运行方式见 README。

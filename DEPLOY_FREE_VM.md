# 免费虚拟机部署（待实际主机验证）

本配置适用于 Oracle Always Free Ubuntu 主机，也可用于已有 Linux 主机。
没有创建任何云资源，也没有启用任何付费套餐。当前线上 Render 不会因这些文件自动迁移。

## 免费资源前提

2026-09-21 核对的 Oracle 官方文档列出 A1 免费额度为每月 1,500 OCPU 小时、9,000 GB 内存小时，
对应 Always Free 账号 2 OCPU / 12 GB 内存。控制台实际额度和同账号已有资源必须一起核对。
选择 home region 的 VM.Standard.A1.Flex，Ubuntu ARM64；启动盘也必须在账号剩余免费额度内。
仅使用 Always Free 资源，不升级付费账号、不使用 30 天试用金资源来替代长期免费额度。
若区域无免费容量，停止创建，不能用付费实例替代。

参考：https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm

## 启动

主机需要 Docker Engine 和 Docker Compose 插件。仓库 Dockerfile 使用多架构基础镜像，
但 ARM64 完整构建仍须在实际主机验证，不能把本地配置检查当作部署成功。

在主机克隆仓库，进入目录，复制 `.env.example` 为 `.env`。
仅填写翻译所需的 API Key、Base URL、模型名和强随机 APP_ACCESS_TOKEN；不要复制 RENDER_API_KEY。
默认模型保留 `qwen3.7-flash`，其他模型必须使用用户提供的精确名称。

```sh
chmod 600 .env
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 translator
```

应用只监听主机本地 8000 端口。无域名时，在自己的电脑使用 SSH 隧道：

```sh
ssh -L 8000:127.0.0.1:8000 ubuntu@主机IP
```

随后访问 http://localhost:8000，可在不购买域名的情况下使用。
模型调用沿用现有服务，云主机免费不代表模型服务免费。

## 已有域名时公开 HTTPS

将已有域名 A 记录指向主机，在 `.env` 增加 `SITE_DOMAIN=你的域名`，
并允许 Oracle 网络规则和主机防火墙的 TCP 80/443 入站。

```sh
docker compose -f compose.yaml -f deploy/compose.https.yaml up -d --build
```

Caddy 自动申请 HTTPS 证书。无已有域名时先使用 SSH 隧道，不需要购买域名。

## 数据保留与验收

SQLite 任务记录、上传文件、译文均位于 `translator-data` 持久卷。
容器重建和正常重启不会删除该卷；不要运行 `docker compose down -v`。
正在执行的任务重启后会明确标记失败，已上传文件与已完成结果保留；尚未实现自动断点续翻。
浏览器会话决定文件归属，换浏览器、清除 Cookie 或换网站地址不会自动迁移旧会话。

上线前必须完成：

1. 用此前实际失败的 PPT 运行到 100%，下载原格式译文和双栏 PDF，检查全部页数。
2. 记录 `docker stats --no-stream`，确认有内存余量。
3. 重启容器，在同一浏览器确认完成任务、预览和下载仍可用。
4. 测试运行中重启：任务应显示中断，不能显示任务不存在。

## BabelDoc 参考范围

参考 https://github.com/C0nstFoL/BabelDoc 的 Compose 持久化做法：历史、输出和缓存保存在容器外。
其 README 主要面向 PDF 翻译，并不等于完整支持 PPTX 原格式翻译；本次没有替换翻译引擎。
增加持久存储可以解决重启后记录丢失，但不能单独解决所有内存问题或保证任意文件成功。

# 课件/论文智能双语对照翻译系统 - 云端 Render 部署指南

本指南将协助您将本项目**免费部署到云端 Render 平台（无需在自己电脑上保持开机和运行命令行）**。部署成功后，您和朋友可以在任何手机、平板、电脑的浏览器上直接打开公网网址（例如 `https://bilingual-doc-translator.onrender.com`）随时随地使用！

---

## 🌟 为什么选择 Render？

- **完全免费**：Render 提供免费的 Web Service 套餐；
- **免本地电脑开机**：全天候运行在云端服务器；
- **自带免费 HTTPS 安全证书**；
- **自动持续部署**：只要您的 GitHub 仓库有代码更新，Render 会自动重新构建发布。

---

## 🚀 三步极简部署流程

### 第一步：将本项目推送到您的 GitHub 仓库

如果您尚未将代码推送到 GitHub，请在终端按以下步骤操作：

1. 打开 [GitHub](https://github.com)，点击右上角 **New repository**，创建一个新的私有或公开仓库（例如命名为 `bilingual-doc-translator`）；
2. 在本地项目根目录终端执行以下命令：

```bash
# 1. 初始化并提交代码（若尚未提交）
git add .
git commit -m "feat: 课件高保真图文无损对照翻译系统与 Render 容器化配置"

# 2. 绑定远程 GitHub 仓库（请替换为您的实际 GitHub 仓库地址）
git remote add origin https://github.com/您的用户名/bilingual-doc-translator.git

# 3. 推送代码到 GitHub
git branch -M main
git push -u origin main
```

---

### 第二步：在 Render 上关联仓库并一键部署

1. 访问 [Render 官网](https://render.com/) 并注册/登录账号（推荐直接使用 GitHub 账号一键登录）；
2. 登录后进入控制台，点击右上角 **“New +”** 按钮，选择 **“Web Service”**；
3. 选择 **“Build and deploy from a Git repository”**，并点击 **“Connect a repository”** 授权连接您的 GitHub；
4. 找到刚刚推送的 `bilingual-doc-translator` 仓库，点击 **“Connect”**；
5. Render 会自动读取仓库中的配置，您只需确认以下两项：
   - **Language / Runtime**：选择 **Docker**（Render 会全自动使用项目中的 `Dockerfile` 进行打包）；
   - **Instance Type**：选择 **Free**（完全免费套餐）；
6. （可选）环境变量设置：
   - 在底部的 **Environment Variables** 中，添加变量名 `DASHSCOPE_API_KEY`，值为您的通义千问 API 密钥（系统内已内置默认密钥，此处配置可方便直接生效）；
7. 点击最下方的 **“Deploy Web Service”** 按钮！

---

### 第三步：大功告成！获取专属公网网址

- Render 将自动拉取代码、构建前端静态页面、安装 Python 核心组件与 Linux 中文字体库（构建过程约 2~3 分钟）；
- 构建完成后，状态会变为绿色的 **“Live”**；
- 在页面顶部，您会看到一个专属的公网链接，例如：
  👉 `https://bilingual-doc-translator-xxxx.onrender.com`
- 点击即可直接在浏览器打开使用，手机、平板均可流畅体验！

---

## 🛠️ 其他可选的免费云端托管平台

除了 Render 之外，本项目预置的 Docker 容器规范也完全兼容以下平台：

| 平台 | 特点 | 部署方式 |
| :--- | :--- | :--- |
| **Railway** ([railway.app](https://railway.app/)) | 性能极高，每月有免费使用额度 | 绑定 GitHub 一键识别 Dockerfile 部署 |
| **Zeabur** ([zeabur.com](https://zeabur.com/)) | 针对国内网络优化良好，支持一键部署 | 绑定 GitHub 自动识别 |
| **Hugging Face Spaces** | 适合 AI 应用，永久免费 | 创建 Docker Space 后 git push 即可 |

---

## ❓ 常见问题排查 (FAQ)

1. **首次打开 Render 网址有点慢？**
   - Render 免费套餐在 15 分钟无访问后会进入休眠状态，休眠后首次访问需要约 30 秒唤醒，唤醒后即恢复高速响应。
2. **云端生成的 PDF 中文字体会乱码吗？**
   - 不会。我们在 `Dockerfile` 中已预装了 Linux 官方的 `fonts-noto-cjk`（Google Noto 思源黑体），在云端服务器中生成的中文 PDF 和预览图清晰锐利，绝无方块乱码。

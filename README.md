# 网页抓取助手 (Web Scraper)

一个基于 Flask + Playwright 的网页内容抓取工具，支持将网页内容转换为 Markdown 格式并下载图片到本地。

## 功能特点

- **多平台支持**：微信公众号、知乎、Twitter/X、普通网页
- **内容提取**：自动提取网页标题、正文内容
- **图片下载**：自动下载文章配图到本地
- **Markdown 导出**：将内容转换为 Markdown 格式，图片引用指向本地文件
- **批量抓取**：支持批量 URL 抓取
- **自定义路径**：可自定义保存路径
- **桌面快捷方式**：提供 macOS .app 桌面启动器

## 技术栈

- **后端**: Python Flask
- **动态渲染**: Playwright (用于反爬虫网站)
- **HTML解析**: BeautifulSoup
- **前端**: 原生 HTML/CSS/JavaScript
- **跨域**: Flask-CORS

## 文件结构

```
web-scraper-project/
├── server.py              # Flask 后端服务器
├── web-scraper-app.html   # 前端界面
├── start-scraper.sh       # 命令行启动脚本
├── 网页抓取助手.app/       # macOS 桌面应用
│   └── Contents/
│       ├── Info.plist     # 应用配置
│       └── MacOS/
│           └── launcher   # 启动脚本
└── README.md              # 本文档
```

## 安装依赖

```bash
pip install flask flask-cors requests beautifulsoup4
pip install playwright  # 可选，用于动态网站
playwright install chromium  # 安装浏览器
```

## 使用方法

### 方式一：命令行启动

```bash
cd web-scraper-project
python3 server.py
```

然后在浏览器打开 http://localhost:5555

### 方式二：使用启动脚本

```bash
./start-scraper.sh
```

### 方式三：macOS 桌面应用

双击 `网页抓取助手.app` 即可启动

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/config` | GET | 获取配置信息 |
| `/api/config` | POST | 更新配置 |
| `/api/preview` | POST | 预览网页内容 |
| `/api/scrape` | POST | 抓取并保存网页 |
| `/api/open-folder` | POST | 打开文件夹 |
| `/api/browse-folder` | GET | 浏览文件夹 |

## 支持的网站

| 网站 | 抓取方式 | 备注 |
|------|----------|------|
| 微信公众号 | 静态请求 | 需要特殊 Headers |
| 知乎 | Playwright | 动态渲染绕过反爬 |
| Twitter/X | Playwright | 动态渲染 |
| 普通网页 | 静态请求 | 自动检测编码 |

## 配置说明

配置文件保存在 `~/.web-scraper-config.json`

默认保存路径: `~/Downloads/web-scraper/`

## 开发历程

1. **v1.0 初始版本**
   - 基础 Flask 服务器
   - 微信公众号内容抓取
   - 图片下载和 Markdown 转换

2. **功能增强**
   - 添加知乎支持 (使用 Playwright)
   - 添加 Twitter/X 支持
   - 批量抓取功能
   - macOS 桌面应用

3. **问题修复**
   - 修复端口配置不一致问题 (5000 -> 5555)
   - 修复知乎 403 错误 (添加到动态网站列表)
   - 修复代码语法错误

## 注意事项

- 部分网站可能有反爬虫机制，请合理使用
- Playwright 需要安装 Chromium 浏览器
- 建议在抓取前先预览内容

## 许可证

MIT License

---

开发时间：2026年3月

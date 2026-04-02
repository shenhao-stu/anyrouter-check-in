<div align="center">

# 🚀 AnyRouter Check-In

**Multi-platform, multi-account auto check-in for NewAPI / OneAPI sites**

[![GitHub Actions](https://github.com/shenhao-stu/anyrouter-check-in/workflows/AnyRouter%20%E8%87%AA%E5%8A%A8%E7%AD%BE%E5%88%B0/badge.svg)](https://github.com/shenhao-stu/anyrouter-check-in/actions)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Playwright](https://img.shields.io/badge/playwright-enabled-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000?logo=ruff&logoColor=white)](https://github.com/astral-sh/ruff)
[![License](https://img.shields.io/github/license/shenhao-stu/anyrouter-check-in?color=blue)](LICENSE)
[![Stars](https://img.shields.io/github/stars/shenhao-stu/anyrouter-check-in?style=social)](https://github.com/shenhao-stu/anyrouter-check-in/stargazers)

[简体中文](#-功能特性) · [English](#-features)

**⭐ 维护开源不易，如果本项目帮助到了你，请帮忙点个 Star，谢谢！**

</div>

---

## ✨ 功能特性

- 🌐 **多平台支持** — 兼容所有 NewAPI / OneAPI 站点
- 👥 **多账号签到** — 同一平台多账号同时签到
- 🔌 **插件一键添加** — Chrome 扩展 / 油猴脚本自动注册新平台，无需手动改 Secrets
- 🔄 **自动重试** — 5xx / 网络超时自动重试，抗抖动
- 🛡️ **WAF 绕过** — Playwright 自动获取 WAF cookies
- 📣 **多渠道通知** — 飞书 / 钉钉 / 企微 / Telegram / Email / Bark / Gotify / PushPlus / Server 酱
- ⏰ **定时执行** — GitHub Actions 每 6 小时自动运行

> 内置支持 [AnyRouter](https://anyrouter.top/register?aff=gSsN) 和 [AgentRouter](https://agentrouter.org)，其它平台通过插件或 `PROVIDERS` secret 一键接入。

推荐搭配 [Auo](https://github.com/millylee/auo) — 支持任意 Claude Code Token 切换的工具。

---

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────────┐
│                  GitHub Actions                      │
│  ┌───────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Secrets   │→ │ checkin  │→ │ Notifications    │  │
│  │ injection │  │ .py      │  │ (飞书/钉钉/TG…)  │  │
│  └───────────┘  └──────────┘  └──────────────────┘  │
└────────────────────────▲────────────────────────────┘
                         │ push secrets
          ┌──────────────┴──────────────┐
          │  Chrome Extension /         │
          │  Tampermonkey Userscript    │
          │  (auto-sync cookies &       │
          │   register new platforms)   │
          └─────────────────────────────┘
```

---

## 🚀 快速开始

### 1️⃣ Fork 本仓库

点击右上角 **Fork** 按钮。

### 2️⃣ 安装插件并配置 GitHub PAT

推荐使用 **Chrome 扩展**或**油猴脚本**（见 [下方详细说明](#-chrome-扩展anyrouter-cookie-updater)）自动同步 cookie。

插件需要一个 GitHub Personal Access Token（PAT）：

1. 访问 [GitHub Settings → Fine-grained tokens](https://github.com/settings/tokens?type=beta)
2. 新建 token，选择你 fork 的仓库，开启 **Secrets** 的 Read & Write 权限
3. 将 token 填入插件设置面板

### 3️⃣ 在插件中添加账号

```json
[
  { "domain": "https://anyrouter.top" },
  { "domain": "https://agentrouter.org" },
  { "domain": "https://api.freestyle.cc.cd" },
  { "domain": "https://computetoken.ai" }
]
```

每行只需填写 `domain`，插件会自动：
- 🍪 提取浏览器 `session` cookie
- 🔍 调用 `/api/user/self` 解析 `api_user`
- 🔑 生成 `ANYROUTER_ACCOUNT_{api_user}_{PROVIDER}` secret 并推送
- 📦 更新 `PROVIDERS` secret，自动注册新平台

### 4️⃣ 设置 Environment Secret（仅首次）

1. 仓库 **Settings → Environments → New environment** → 新建 `production`
2. 添加 secret `ANYROUTER_ACCOUNTS`（账号 JSON 数组）

> 💡 如果所有账号都通过 `ANYROUTER_ACCOUNT_*` 独立管理（推荐），`ANYROUTER_ACCOUNTS` 可设为 `[]`。

### 5️⃣ 启用 GitHub Actions

在 **Actions** 选项卡启用 "AnyRouter 自动签到" workflow，点击 **Run workflow** 手动触发一次验证。

---

## 📋 多账号配置格式

### ANYROUTER_ACCOUNTS（基础账号列表）

```json
[
  {
    "name": "AnyRouter 主账号",
    "cookies": { "session": "account1_session_value" },
    "api_user": "123456"
  },
  {
    "name": "AgentRouter 备用",
    "provider": "agentrouter",
    "cookies": { "session": "account2_session_value" },
    "api_user": "789012"
  }
]
```

| 字段 | 必填 | 说明 |
| :--- | :---: | :--- |
| `cookies` | ✅ | 身份验证 cookies |
| `api_user` | ✅ | 请求头 `new-api-user` 的值 |
| `provider` | ❌ | 服务商标识，默认 `anyrouter` |
| `name` | ❌ | 显示名称，用于日志和通知 |

> 📌 `anyrouter` 和 `agentrouter` 已内置；其它平台通过 `PROVIDERS` secret 或插件自动注册。

### 🔑 获取 cookies 和 api_user

通过 F12 开发者工具：

- **session** → Application → Cookies → 复制 `session` 值（重新登录后获取，有效期约 1 个月）
- **api_user** → Network → 过滤 Fetch/XHR → 找到含 `New-Api-User` 请求头的请求

<details>
<summary>📸 截图参考</summary>

![获取 cookies](./assets/request-session.png)
![获取 api_user](./assets/request-api-user.png)

</details>

---

## 🗂️ 单账号独立管理（ANYROUTER_ACCOUNT_*）

推荐方式。每个账号单独一个 secret，插件自动维护。

### 命名规范

```
ANYROUTER_ACCOUNT_{api_user}_{PROVIDER}
```

示例：
```
ANYROUTER_ACCOUNT_123456_ANYROUTER
ANYROUTER_ACCOUNT_789012_AGENTROUTER
ANYROUTER_ACCOUNT_7535_FREESTYLE
ANYROUTER_ACCOUNT_760_COMPUTETOKEN
```

> ⚠️ `api_user` 是各平台内部自增 ID，不同平台间可能重复，必须加平台标识才能唯一区分。

### Secret 内容格式

```json
{
  "cookies": { "session": "session_value" },
  "api_user": "760",
  "provider": "computetoken",
  "domain": "https://computetoken.ai"
}
```

### 合并规则

- 🔄 独立 secret 与 `ANYROUTER_ACCOUNTS` 中 `api_user` 匹配时，字段会**覆盖**主配置
- ➕ 无匹配时作为新账号追加
- 🔑 去重键为 `(api_user, provider)` 组合

---

## 🌍 新平台接入（全自动）

只需在插件账号列表中添加新域名，点击"同步所有账号"，插件自动完成：

1. 🍪 提取该站点的 session cookie
2. 🔑 推送 `ANYROUTER_ACCOUNT_*` secret（含 `provider` 和 `domain`）
3. 📦 更新 `PROVIDERS` secret

**全程无需手动修改任何 GitHub Secret。**

### 🏷️ 平台 Tag 命名规则

| 域名 | 自动生成 Tag |
| :--- | :--- |
| `https://anyrouter.top` | `ANYROUTER` |
| `https://api.freestyle.cc.cd` | `FREESTYLE` |
| `https://computetoken.ai` | `COMPUTETOKEN` |
| `https://my-custom-api.example.com` | `MY` |

> 前缀 `www`、`api`、`app`、`new`、`newapi`、`welfare` 会被自动跳过。

---

## ⚙️ 手动配置 Provider（可选）

若不使用插件，可手动配置 `PROVIDERS` secret：

<details>
<summary>📝 基础配置（仅域名）</summary>

```json
{
  "computetoken": { "domain": "https://computetoken.ai" },
  "freestyle": { "domain": "https://api.freestyle.cc.cd" }
}
```

</details>

<details>
<summary>📝 完整配置（自定义路径 + WAF）</summary>

```json
{
  "customrouter": {
    "domain": "https://custom.example.com",
    "login_path": "/auth/login",
    "sign_in_path": "/api/checkin",
    "user_info_path": "/api/profile",
    "api_user_key": "New-Api-User",
    "bypass_method": "waf_cookies",
    "waf_cookie_names": ["acw_tc", "cdn_sec_tc", "acw_sc__v2"]
  }
}
```

</details>

| 字段 | 必填 | 默认值 | 说明 |
| :--- | :---: | :--- | :--- |
| `domain` | ✅ | — | 服务商域名 |
| `login_path` | ❌ | `/login` | 登录页路径（WAF 模式） |
| `sign_in_path` | ❌ | `/api/user/sign_in` | 签到 API（404 自动回退 `/api/user/checkin`） |
| `user_info_path` | ❌ | `/api/user/self` | 用户信息 API |
| `api_user_key` | ❌ | `new-api-user` | 请求头用户 ID 键名 |
| `bypass_method` | ❌ | `null` | `"waf_cookies"` 或 `null` |
| `waf_cookie_names` | ❌ | — | WAF cookie 名称列表 |

### 🛡️ 内置平台

| 平台 | WAF | 签到方式 |
| :--- | :---: | :--- |
| `anyrouter` | ✅ waf_cookies | `/api/user/sign_in` |
| `agentrouter` | ✅ waf_cookies | 查询用户信息时自动签到 |
| `heibai` | ✅ turnstile_browser | Playwright 浏览器交互签到 |

> 其余平台通过 `PROVIDERS` secret 或插件自动同步。标准 new-api / one-api 站点使用默认路径，404 时自动回退到 `/api/user/checkin`。

---

## 🧩 Chrome 扩展：AnyRouter Cookie Updater

位于仓库 `AnyRouter Cookie Updater/` 目录。

### 工作原理

1. 🍪 从浏览器 cookie jar 提取 `session` cookie
2. 🔍 调用 `/api/user/self` 解析 `api_user`（优先读 localStorage，零网络请求）
3. 🔐 使用 libsodium sealed box 加密后推送 `ANYROUTER_ACCOUNT_*` secret
4. 📦 同步结束后更新 `PROVIDERS` secret，自动注册非内置平台

### 📥 安装

1. 打开 `chrome://extensions/`
2. 开启右上角"开发者模式"
3. 点击"加载已解压的扩展程序" → 选择 `AnyRouter Cookie Updater/` 目录

### 🔧 配置

| 配置项 | 说明 |
| :--- | :--- |
| 🔑 GitHub PAT | 需要 `Secrets` Read & Write 权限 |
| 👤 仓库 Owner | 你的 GitHub 用户名 |
| 📦 仓库名称 | 如 `anyrouter-check-in` |
| 🏷️ Environment | 如 `production`（留空则推送到 repo secrets） |
| 📋 账号列表 | 每行一个站点，只需填 `domain` |
| ⏰ 同步间隔 | 建议 360 分钟（6 小时），0 = 仅手动 |

---

## 🐒 Tampermonkey 脚本

油猴脚本 `anyrouter-cookie-updater.user.js`，支持 Chrome / Firefox / Edge / Safari。

### 📥 安装

- **方式一（推荐）**：安装 [Tampermonkey](https://www.tampermonkey.net/) 后，直接打开仓库中的 `anyrouter-cookie-updater.user.js`
- **方式二**：Tampermonkey 管理面板 → "添加新脚本" → 粘贴内容保存

### 📋 菜单命令

| 命令 | 说明 |
| :--- | :--- |
| ⚙️ 设置 / 账号配置 | 打开配置面板 |
| 🔄 立即同步本站 | 提取当前站点 cookie 并推送 |
| 🔄 同步所有账号 | 遍历所有账号逐个同步，并更新 `PROVIDERS` |
| 📋 查看日志 | 查看最近 80 条操作日志 |

### 🔄 Chrome 扩展 vs 油猴脚本

| 特性 | Chrome 扩展 | 油猴脚本 |
| :--- | :---: | :---: |
| 支持浏览器 | Chrome / Edge | 全平台 |
| 需要开发者模式 | ✅ | ❌ |
| 后台定时触发 | ✅ | ⚠️ 页面加载时 |
| 跨站点 cookie | ✅ | ⚠️ 需在对应站点 |
| 单账号测试 | ✅ | ✅ |

---

## 📣 通知配置

在仓库 **Settings → Environments → production → Environment secrets** 中添加：

<details>
<summary>📧 邮箱（SMTP）</summary>

| 变量 | 说明 |
| :--- | :--- |
| `EMAIL_USER` | 发件人地址 / SMTP 登录名 |
| `EMAIL_PASS` | 密码 / 授权码 |
| `EMAIL_SENDER` | 发件人显示地址（可选） |
| `CUSTOM_SMTP_SERVER` | 自定义 SMTP 服务器（可选） |
| `EMAIL_TO` | 收件人地址 |

</details>

<details>
<summary>🤖 钉钉机器人</summary>

`DINGDING_WEBHOOK` — Webhook 地址（自定义关键词填 `AnyRouter`）

</details>

<details>
<summary>🐦 飞书机器人</summary>

`FEISHU_WEBHOOK` — Webhook 地址

</details>

<details>
<summary>💬 企业微信机器人</summary>

`WEIXIN_WEBHOOK` — Webhook 地址

</details>

<details>
<summary>📱 PushPlus / Server 酱</summary>

- `PUSHPLUS_TOKEN` — PushPlus Token
- `SERVERPUSHKEY` — Server 酱 SendKey

</details>

<details>
<summary>✈️ Telegram Bot</summary>

- `TELEGRAM_BOT_TOKEN` — Bot Token
- `TELEGRAM_CHAT_ID` — Chat ID

</details>

<details>
<summary>🔔 Gotify / Bark</summary>

**Gotify:**
- `GOTIFY_URL` — 服务地址
- `GOTIFY_TOKEN` — 应用访问令牌
- `GOTIFY_PRIORITY` — 优先级（1-10，默认 9）

**Bark:**
- `BARK_KEY` — APP 打开即可看到
- `BARK_SERVER` — 自建服务器地址（可选，默认 `https://api.day.app`）

</details>

---

## 🔧 故障排除

| 现象 | 排查方向 |
| :--- | :--- |
| ❌ 401 错误 | cookie 已过期，重新登录后插件同步即可 |
| ⚠️ 502 / 连接超时 | 服务端暂时不可用，脚本会自动重试 |
| 🔀 路由到错误平台 | 检查 `PROVIDERS` secret；重新执行插件"同步所有账号" |
| 🍪 cookie 提取失败 | 确认已在浏览器中登录该站点 |
| 🔍 api_user 解析失败 | 确认站点为 NewAPI / OneAPI 架构 |
| 🆕 新平台全部 401 | `PROVIDERS` 未包含该平台，执行插件同步后重新触发 Actions |

---

## 🛠️ 本地开发

```bash
# 安装依赖
uv sync --dev

# 安装 Playwright 浏览器
uv run playwright install chromium

# 配置环境变量
cp .env.example .env  # 编辑 .env 填入账号信息

# 运行签到
uv run checkin.py

# 运行测试
uv run pytest tests/
uv run pytest tests/ --cov=. --cov-report=html
```

---

## 🤝 贡献指南

欢迎贡献！提交 PR 前请确保：

```bash
uv run pre-commit install
uv run ruff check . && uv run ruff format .
uv run mypy .
uv run pytest tests/ --cov=.
```

本项目使用 Ruff（代码风格）、MyPy（类型检查）、Bandit（安全扫描）、Pytest（测试）和 pre-commit 保证代码质量。

---

## 📝 更新日志

<details>
<summary><b>v1.7</b> — 2026-03-17 网络异常自动重试</summary>

- 🔄 签到请求遇到 HTTP 5xx / 网络异常时自动重试（间隔 5 秒）
- 🔄 用户信息获取同样支持重试
- 📋 重试日志清晰标注 `[RETRY]`

</details>

<details>
<summary><b>v1.6</b> — 2026-03-17 插件一键注册新平台</summary>

- 🔌 插件同步时自动更新 `PROVIDERS` secret
- 🐛 修复新平台路由到 anyrouter 的 bug
- 🔑 签到脚本自动注册 provider（双重保险）
- 🐛 修复多账号同一平台去重 bug（改用 `(api_user, provider)` 组合键）
- 🏷️ 新增动态 provider tag 生成

</details>

<details>
<summary><b>v1.5</b> — 2026-03-12 Cookie 提取与 api_user 解析修复</summary>

- 🐛 修复 Cookie 竞态条件（两阶段提取）
- 🐛 修复 api_user 解析失败（优先 localStorage）
- 🐛 修复 tab 生命周期 bug

</details>

<details>
<summary><b>v1.4</b> — 2026-03-11 加密实现修复</summary>

- 🔐 修复 GitHub Secrets 加密 bug（改用 libsodium sealed box）
- 📦 Chrome 扩展引入 libsodium，替换 TweetNaCl

</details>

<details>
<summary><b>v1.3</b> — 2026-03-11 Secret 命名规范统一</summary>

- 🏷️ 统一格式为 `{api_user}_{PROVIDER}`

</details>

<details>
<summary><b>v1.2</b> — 2026-03-11 Tampermonkey 脚本 + 导入功能</summary>

- 🐒 新增油猴脚本，功能与 Chrome 扩展对等
- 📥 新增从 ANYROUTER_ACCOUNTS 一键导入

</details>

<details>
<summary><b>v1.1</b> — 2026-03-11 Chrome 扩展体验优化</summary>

- 🔄 双模式账号配置（列表 / JSON）
- 🔍 api_user 自动获取

</details>

<details>
<summary><b>v1.0</b> — 初始版本</summary>

- 🚀 多账号自动签到
- 📣 多渠道通知
- 🔑 ANYROUTER_ACCOUNT_* 独立管理
- 🧩 Chrome 扩展 AnyRouter Cookie Updater

</details>

---

## 📊 Star History

<a href="https://star-history.com/#shenhao-stu/anyrouter-check-in&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=shenhao-stu/anyrouter-check-in&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=shenhao-stu/anyrouter-check-in&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=shenhao-stu/anyrouter-check-in&type=Date" />
 </picture>
</a>

---

## ⚖️ 免责声明

本脚本仅用于学习和研究目的，使用前请确保遵守相关网站的使用条款。

---

<!-- English Documentation -->

<div align="center">

# 🌍 English Documentation

</div>

## ✨ Features

- 🌐 **Multi-platform** — Compatible with all NewAPI / OneAPI sites
- 👥 **Multi-account** — Check in multiple accounts on the same platform simultaneously
- 🔌 **One-click onboarding** — Chrome extension / Tampermonkey auto-registers new platforms
- 🔄 **Auto-retry** — Retries on 5xx / network timeouts
- 🛡️ **WAF bypass** — Playwright auto-fetches WAF cookies
- 📣 **Multi-channel notifications** — Feishu / DingTalk / WeCom / Telegram / Email / Bark / Gotify / PushPlus
- ⏰ **Scheduled execution** — GitHub Actions runs every 6 hours

> Built-in support for [AnyRouter](https://anyrouter.top/register?aff=gSsN) and [AgentRouter](https://agentrouter.org). Other platforms are onboarded via the browser extension or `PROVIDERS` secret.

## 🚀 Quick Start

### 1️⃣ Fork this repository

### 2️⃣ Install the browser extension & configure GitHub PAT

Use the **Chrome extension** or **Tampermonkey userscript** to auto-sync cookies.

1. Create a [Fine-grained PAT](https://github.com/settings/tokens?type=beta) with **Secrets** Read & Write permission
2. Enter the token in the extension settings

### 3️⃣ Add accounts in the extension

```json
[
  { "domain": "https://anyrouter.top" },
  { "domain": "https://agentrouter.org" }
]
```

The extension automatically:
- 🍪 Extracts `session` cookie from the browser
- 🔍 Resolves `api_user` via `/api/user/self`
- 🔑 Pushes `ANYROUTER_ACCOUNT_{api_user}_{PROVIDER}` secret
- 📦 Updates `PROVIDERS` secret to register new platforms

### 4️⃣ Set up Environment Secret (first time only)

1. Go to **Settings → Environments** → create `production`
2. Add secret `ANYROUTER_ACCOUNTS` (JSON array, or `[]` if using individual secrets)

### 5️⃣ Enable GitHub Actions

Enable the "AnyRouter 自动签到" workflow and trigger a manual run to verify.

## 📋 Account Configuration

### Individual Account Secrets (Recommended)

Each account gets its own secret:

```
ANYROUTER_ACCOUNT_{api_user}_{PROVIDER}
```

Secret value format:
```json
{
  "cookies": { "session": "session_value" },
  "api_user": "760",
  "provider": "computetoken",
  "domain": "https://computetoken.ai"
}
```

### Custom Providers

Add a `PROVIDERS` environment secret:

```json
{
  "computetoken": { "domain": "https://computetoken.ai" },
  "freestyle": { "domain": "https://api.freestyle.cc.cd" }
}
```

Standard new-api / one-api sites use default paths (`/api/user/self`, `/api/user/sign_in`, with automatic fallback to `/api/user/checkin` on 404).

## 📣 Notifications

Configure notification channels via environment secrets:

| Channel | Required Secrets |
| :--- | :--- |
| 📧 Email (SMTP) | `EMAIL_USER`, `EMAIL_PASS`, `EMAIL_TO` |
| 🤖 DingTalk | `DINGDING_WEBHOOK` |
| 🐦 Feishu (Lark) | `FEISHU_WEBHOOK` |
| 💬 WeCom | `WEIXIN_WEBHOOK` |
| 📱 PushPlus | `PUSHPLUS_TOKEN` |
| 📱 Server Chan | `SERVERPUSHKEY` |
| ✈️ Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| 🔔 Gotify | `GOTIFY_URL`, `GOTIFY_TOKEN` |
| 🔔 Bark | `BARK_KEY` |

## 🔧 Troubleshooting

| Issue | Solution |
| :--- | :--- |
| ❌ HTTP 401 | Cookie expired — re-login and let the extension sync |
| ⚠️ 502 / timeout | Server temporarily unavailable, auto-retry handles this |
| 🔀 Wrong platform | Check `PROVIDERS` secret; re-run extension "Sync All" |
| 🆕 New platform 401 | `PROVIDERS` missing — run extension sync, then re-trigger Actions |

## 🛠️ Local Development

```bash
uv sync --dev
uv run playwright install chromium
uv run checkin.py

# Tests
uv run pytest tests/
```

---

<div align="center">

Made with ❤️ by [shenhao-stu](https://github.com/shenhao-stu)

</div>



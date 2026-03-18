# Any Router 多账号自动签到

[![GitHub Actions](https://github.com/shenhao-stu/anyrouter-check-in/workflows/AnyRouter%20%E8%87%AA%E5%8A%A8%E7%AD%BE%E5%88%B0/badge.svg)](https://github.com/shenhao-stu/anyrouter-check-in/actions)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![License](https://img.shields.io/github/license/millylee/anyrouter-check-in)](LICENSE)

多平台多账号自动签到，理论上支持所有 NewAPI / OneAPI 平台，内置支持 AnyRouter、AgentRouter、Freestyle、XingyunGEPT、Sorai、APIKey，其它未知平台通过插件一键注册，无需手动修改 GitHub Secrets。

**配合 [Chrome 扩展 / 油猴脚本](#chrome-扩展anyrouter-cookie-updater) 食用效果更好** — 自动从浏览器提取 session cookie 并推送到 GitHub Secrets，同时**自动注册新平台**，cookie 过期或新增平台时无需手动编辑任何环境变量。

推荐搭配使用 [Auo](https://github.com/millylee/auo)，支持任意 Claude Code Token 切换的工具。

**维护开源不易，如果本项目帮助到了你，请帮忙点个 Star，谢谢！**

用于 Claude Code 中转站 Any Router 网站多账号每日签到，一次 $25，限时注册即送 100 美金，[点击这里注册](https://anyrouter.top/register?aff=gSsN)。业界良心，支持 Claude Sonnet 4.5、GPT-5-Codex、Claude Code 百万上下文（使用 `/model sonnet[1m]` 开启），`gemini-2.5-pro` 模型。

---

## 功能特性

- ✅ 多平台（兼容 NewAPI 与 OneAPI）
- ✅ 单个 / 多账号自动签到
- ✅ **同一平台多账号**同时签到
- ✅ **插件一键添加新平台**，无需手动修改 GitHub Secrets
- ✅ 多种机器人通知（可选）
- ✅ 绕过 WAF 限制
- ✅ 网络异常自动重试（5xx、连接超时等）

---

## 快速开始

### 1. Fork 本仓库

点击右上角的 "Fork" 按钮，将本仓库 fork 到你的账户。

### 2. 安装插件并配置 GitHub PAT

推荐使用 **Chrome 扩展**或**油猴脚本**（见 [下方详细说明](#chrome-扩展anyrouter-cookie-updater)）自动同步 cookie。

插件需要一个 GitHub Personal Access Token（PAT）：

1. 访问 [GitHub Settings → Developer settings → Fine-grained tokens](https://github.com/settings/tokens?type=beta)
2. 新建 token，选择你 fork 的仓库，开启 **Secrets** 的 Read & Write 权限
3. 将 token 填入插件设置面板

### 3. 在插件中添加账号

打开插件设置面板，在账号列表中添加你要签到的每个站点：

```json
[
  { "domain": "https://anyrouter.top" },
  { "domain": "https://agentrouter.org" },
  { "domain": "https://api.freestyle.cc.cd" },
  { "domain": "https://computetoken.ai" }
]
```

每行只需填写 `domain`。插件会：

1. 实时从浏览器提取当前 `session` cookie
2. 调用 `/api/user/self` 自动解析 `api_user`
3. 自动生成 `ANYROUTER_ACCOUNT_{api_user}_{PROVIDER}` 格式的 secret 并推送
4. **自动更新 `PROVIDERS` secret**，将新平台注册到签到脚本，无需手动编辑

### 4. 设置 GitHub Environment Secret（仅首次）

插件的自动同步会处理大部分配置，但首次运行前需要手动设置 `ANYROUTER_ACCOUNTS`（基础账号列表）：

1. 在你 fork 的仓库，进入 **Settings → Environments → New environment**
2. 新建名为 `production` 的环境
3. 点击 **Add environment secret**，添加：
   - Name: `ANYROUTER_ACCOUNTS`
   - Value: 你的账号 JSON 数组（见下方格式说明）

> **提示**：如果你的所有账号都通过 `ANYROUTER_ACCOUNT_*` 独立 secret 管理（推荐方式），`ANYROUTER_ACCOUNTS` 可以设置为空数组 `[]`。

### 5. 启用并测试 GitHub Actions

1. 在仓库的 **Actions** 选项卡中找到 "AnyRouter 自动签到" workflow，点击启用
2. 点击 **Run workflow** 手动触发一次，确认运行正常

---

## 多账号配置格式

### ANYROUTER_ACCOUNTS（基础账号列表）

支持单个与多个账号，可选 `name` 和 `provider` 字段：

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

**字段说明**：

| 字段 | 是否必填 | 说明 |
| --- | --- | --- |
| `cookies` | 必填 | 用于身份验证的 cookies |
| `api_user` | 必填 | 请求头 `new-api-user` 的值 |
| `provider` | 可选 | 服务商标识，默认 `anyrouter` |
| `name` | 可选 | 账号显示名称，用于日志和通知 |

> `anyrouter`、`agentrouter`、`freestyle`、`xingyungept`、`sorai`、`apikey` 已内置配置；其它平台可通过 `PROVIDERS` secret 或插件自动注册。

### 获取 cookies 和 api_user

通过 F12 开发者工具：

- **session**：Application 面板 → Cookies → 复制 `session` 值。建议重新登录后再获取，有效期约 1 个月。
- **api_user**：Network 面板 → 过滤 Fetch/XHR → 找到含 `New-Api-User` 请求头的请求，正常为 5 位数字。

![获取 cookies](./assets/request-session.png)

![获取 api_user](./assets/request-api-user.png)

---

## 单账号独立管理（ANYROUTER_ACCOUNT_* 前缀）

推荐方式。每个账号的 cookie 单独存一个 secret，插件自动维护，某个账号过期时只更新对应 secret 即可。

### Secret 命名规范

```
ANYROUTER_ACCOUNT_{api_user}_{PROVIDER}
```

示例：

```
ANYROUTER_ACCOUNT_123456_ANYROUTER
ANYROUTER_ACCOUNT_789012_AGENTROUTER
ANYROUTER_ACCOUNT_7535_FREESTYLE
ANYROUTER_ACCOUNT_760_COMPUTETOKEN
ANYROUTER_ACCOUNT_883_COMPUTETOKEN
```

> **为什么必须带平台标识？** `api_user` 是各平台内部自增 ID，不同平台间完全独立，相同数字可能代表完全不同的账号。必须加上平台标识才能唯一区分。

### Secret 内容格式

插件推送的 secret 值现在包含 `provider` 和 `domain` 字段：

```json
{
  "cookies": { "session": "session_value" },
  "api_user": "760",
  "provider": "computetoken",
  "domain": "https://computetoken.ai"
}
```

签到脚本读取这些字段后，即使平台不在内置列表中，也能通过 `domain` 字段自动注册并正确路由。

### 合并规则

- 若 `ANYROUTER_ACCOUNTS` 中存在 `api_user` 与独立 secret 后缀匹配的账号，独立 secret 的字段会**覆盖**主配置（适合仅更新 cookie）
- 若无匹配，独立 secret 作为新账号追加
- 去重键为 `(api_user, provider)` 组合，同一平台的相同用户只保留第一个，不同平台的相同 user ID 会各自保留

---

## 新平台接入（全自动）

只需在插件的账号列表中添加新域名，点击"同步所有账号"，插件会自动完成：

1. 从浏览器提取该站点的 session cookie
2. 推送 `ANYROUTER_ACCOUNT_*` secret（含 `provider` 和 `domain` 字段）
3. 更新 `PROVIDERS` secret，将新平台的 `domain` 注册进去

签到脚本读取 `PROVIDERS` 后即可正确路由到新平台，**全程无需手动修改任何 GitHub Secret**。

### 平台 Tag 命名规则

插件根据域名自动生成平台 tag（用于 secret 命名后缀）：

| 域名 | 自动生成的 tag |
| --- | --- |
| `https://anyrouter.top` | `ANYROUTER` |
| `https://api.freestyle.cc.cd` | `FREESTYLE` |
| `https://computetoken.ai` | `COMPUTETOKEN` |
| `https://my-custom-api.example.com` | `MY` |

> 前缀 `www`、`api`、`app`、`new`、`newapi`、`welfare` 会被自动跳过，取后面第一个有意义的部分。

---

## 手动配置自定义 Provider（可选）

若不使用插件，也可手动配置 `PROVIDERS` secret：

### 基础配置（仅域名）

```json
{
  "computetoken": {
    "domain": "https://computetoken.ai"
  },
  "freestyle": {
    "domain": "https://api.freestyle.cc.cd"
  }
}
```

### 完整配置（自定义路径 + WAF 绕过）

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

**字段说明**：

| 字段 | 是否必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `domain` | 必填 | — | 服务商域名 |
| `login_path` | 可选 | `/login` | 登录页路径（仅 WAF 模式使用） |
| `sign_in_path` | 可选 | `/api/user/sign_in` | 签到 API 路径 |
| `user_info_path` | 可选 | `/api/user/self` | 用户信息 API 路径 |
| `api_user_key` | 可选 | `new-api-user` | 请求头用户 ID 键名 |
| `bypass_method` | 可选 | `null` | `"waf_cookies"` 或 `null` |
| `waf_cookie_names` | 可选 | — | WAF cookie 名称列表 |

**`bypass_method` 说明**：

- `null`（默认）：直接使用用户 cookie 请求，适合无 WAF 保护的平台
- `"waf_cookies"`：先用 Playwright 打开浏览器获取 WAF cookie，再执行签到，适合 AnyRouter 类有防护的平台

**内置平台**：

| 平台 | WAF | 签到路径 |
| --- | --- | --- |
| `anyrouter` | waf_cookies | `/api/user/sign_in` |
| `agentrouter` | waf_cookies | 访问用户信息时自动签到 |
| `freestyle` | 无 | `/api/user/sign_in`（404 时自动回退到 `/api/user/checkin`） |
| `xingyungept` | 无 | `/api/user/sign_in`（404 时自动回退到 `/api/user/checkin`） |
| `sorai` | 无 | `/api/user/sign_in`（404 时自动回退到 `/api/user/checkin`） |
| `apikey` | 无 | `/api/user/sign_in`（404 时自动回退到 `/api/user/checkin`） |

---

## 执行计划

- 脚本每 6 小时自动执行一次（GitHub Actions 调度可能延迟 1~1.5 小时）
- 可随时在 Actions 页面手动触发

---

## 注意事项

- 每个账号的 cookie 有效期约 1 个月，过期后报 401 错误，重新登录后插件自动同步即可
- 不同平台的签到时间可能不同，AnyRouter 为每 24 小时可签到一次（非零点重置）
- 支持部分账号失败：只要有账号成功签到，整个 Actions 任务就不会失败
- 请求 200 但出现 Error 1040：官方数据库问题，详见 [#7](https://github.com/millylee/anyrouter-check-in/issues/7)

---

## Chrome 扩展：AnyRouter Cookie Updater

Chrome 扩展位于仓库 `AnyRouter Cookie Updater/` 目录。

### 工作原理

1. 从浏览器 cookie jar 中提取已登录站点的 `session` cookie
2. 调用 `/api/user/self` 解析 `api_user`（优先读 localStorage，无网络请求）
3. 使用 libsodium sealed box 加密后推送 `ANYROUTER_ACCOUNT_*` secret
4. **同步结束后更新 `PROVIDERS` secret**，将非内置平台的 domain 自动注册

### 安装

1. 打开 Chrome，进入 `chrome://extensions/`
2. 开启右上角的"开发者模式"
3. 点击"加载已解压的扩展程序"
4. 选择本仓库中的 `AnyRouter Cookie Updater/` 目录

### 配置

打开扩展弹窗，填写：

| 配置项 | 说明 |
| --- | --- |
| **GitHub PAT** | 需要 `Secrets` Read & Write 权限 |
| **仓库 Owner** | 你的 GitHub 用户名 |
| **仓库名称** | 如 `anyrouter-check-in` |
| **Environment** | 如 `production`（留空则推送到 repository secrets） |
| **账号列表** | 每行一个站点，只需填 `domain` |
| **同步间隔（分钟）** | 建议 360（6 小时），0 表示仅手动触发 |

### 账号列表示例

```json
[
  { "domain": "https://anyrouter.top" },
  { "domain": "https://agentrouter.org" },
  { "domain": "https://api.freestyle.cc.cd" },
  { "domain": "https://computetoken.ai" }
]
```

推荐只填 `domain`，其余字段（`api_user`、`env_key_suffix`、`cookie_name`）均会在同步时自动处理。

### 账号配置字段

| 字段 | 是否必填 | 说明 |
| --- | --- | --- |
| `domain` | 必填 | 站点域名 |
| `api_user` | 可选 | 手填时参与 secret 命名；留空自动从 `/api/user/self` 解析 |
| `env_key_suffix` | 可选 | secret 名称后缀，留空自动生成为 `{api_user}_{PROVIDER}` |
| `cookie_name` | 可选 | 要提取的 cookie 名称，默认 `session` |

### 从 ANYROUTER_ACCOUNTS 一键导入

点击弹窗底部的"📥 导入"按钮，粘贴 `ANYROUTER_ACCOUNTS` 的 JSON 内容（支持多行），扩展会自动提取 `provider` / `domain` 转换为账号列表。支持"导入并覆盖"和"导入并合并（按 domain 去重）"两种模式。

---

## Tampermonkey 脚本：AnyRouter Cookie Updater

油猴脚本文件 `anyrouter-cookie-updater.user.js`，无需安装 Chrome 扩展，在 Chrome / Firefox / Edge / Safari 等支持油猴的浏览器中均可使用。

### 安装

**方式一（推荐）**：安装 [Tampermonkey](https://www.tampermonkey.net/) 后，在仓库中直接打开 `anyrouter-cookie-updater.user.js`，油猴会自动弹出安装确认。

**方式二**：打开 Tampermonkey 管理面板 → "添加新脚本" → 粘贴文件内容保存。

### 添加新站点

在脚本的 `@match` 列表中追加新域名（Tampermonkey 编辑器中修改）：

```js
// @match        https://computetoken.ai/*
// @match        https://api.freestyle.cc.cd/*
```

也可以在设置面板的账号列表中直接添加 domain，同步时脚本会通过 `GM_cookie` 跨域提取 cookie。

### 菜单命令

| 命令 | 说明 |
| --- | --- |
| ⚙️ 设置 / 账号配置 | 打开配置面板 |
| 🔄 立即同步本站 | 提取当前站点 cookie 并推送 |
| 🔄 同步所有账号 | 遍历所有配置账号逐个同步，并更新 `PROVIDERS` |
| 📋 查看日志 | 查看最近 80 条操作日志 |

### Chrome 扩展 vs 油猴脚本

| 特性 | Chrome 扩展 | 油猴脚本 |
| --- | --- | --- |
| 支持浏览器 | Chrome / Edge | Chrome / Firefox / Edge / Safari 等 |
| 需要开发者模式 | ✅ 是 | ❌ 否 |
| 定时触发 | ✅ 后台 alarm，浏览器不开也触发 | ⚠️ 页面加载时检查 |
| 跨站点 cookie | ✅ 任意域名 | ⚠️ 需在对应站点页面运行 |

---

## 开启通知

在仓库 **Settings → Environments → production → Environment secrets** 中添加通知变量。

### 邮箱（SMTP）

- `EMAIL_USER`：发件人地址 / SMTP 登录名
- `EMAIL_PASS`：密码 / 授权码
- `EMAIL_SENDER`：发件人显示地址（可选，默认同 `EMAIL_USER`）
- `CUSTOM_SMTP_SERVER`：自定义 SMTP 服务器（可选）
- `EMAIL_TO`：收件人地址

### 钉钉机器人

- `DINGDING_WEBHOOK`：Webhook 地址（自定义关键词填 `AnyRouter`）

### 飞书机器人

- `FEISHU_WEBHOOK`：Webhook 地址

### 企业微信机器人

- `WEIXIN_WEBHOOK`：Webhook 地址

### PushPlus

- `PUSHPLUS_TOKEN`：Token

### Server 酱

- `SERVERPUSHKEY`：SendKey

### Telegram Bot

- `TELEGRAM_BOT_TOKEN`：Bot Token
- `TELEGRAM_CHAT_ID`：Chat ID

### Gotify

- `GOTIFY_URL`：服务地址（如 `https://your-gotify/message`）
- `GOTIFY_TOKEN`：应用访问令牌
- `GOTIFY_PRIORITY`：消息优先级（1-10，默认 9）

### Bark

- `BARK_KEY`：APP 打开即可看到
- `BARK_SERVER`：自建服务器地址（可选，默认 `https://api.day.app`）

---

## 故障排除

| 现象 | 排查方向 |
| --- | --- |
| 401 错误 | cookie 已过期，重新登录后插件同步即可 |
| 502 / 连接超时 | 目标平台服务端暂时不可用，脚本会自动重试一次（间隔 5 秒），通常无需干预 |
| 账号路由到错误平台 | 检查 `PROVIDERS` secret 是否包含该平台；重新执行插件"同步所有账号"以自动更新 `PROVIDERS` |
| cookie 提取失败 | 确认已在浏览器中登录该站点；扩展确认已授予"在所有网站上"的 host 权限 |
| api_user 解析失败 | 确认站点为 NewAPI / OneAPI 架构；可在账号配置中手动填写 `api_user` |
| 新平台签到全部 401 | `PROVIDERS` 未包含该平台，执行插件"同步所有账号"后重新触发 Actions |

---

## 本地开发

```bash
# 安装所有依赖
uv sync --dev

# 安装 Playwright 浏览器
uv run playwright install chromium

# 创建 .env 文件配置账号
# ANYROUTER_ACCOUNTS=[{"name":"账号1","cookies":{"session":"xxx"},"api_user":"12345"}]
# PROVIDERS={"computetoken":{"domain":"https://computetoken.ai"}}

# 运行签到脚本
uv run checkin.py
```

## 测试

```bash
uv sync --dev
uv run playwright install chromium
uv run pytest tests/
uv run pytest tests/ --cov=. --cov-report=html
```

## 贡献指南

欢迎贡献代码！提交 Pull Request 前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

本项目使用 Ruff（代码风格）、MyPy（类型检查）、Bandit（安全扫描）、Pytest（测试）和 pre-commit 保证代码质量。

```bash
uv run pre-commit install
uv run ruff check . && uv run ruff format .
uv run mypy .
uv run pytest tests/ --cov=.
```

---

## 开发日志

### 2026-03-17

#### v1.7 - 网络异常自动重试

- **签到请求自动重试**：遇到 HTTP 5xx（如 502 Bad Gateway）或网络异常（连接超时、`WinError 10060` 等）时，自动等待 5 秒后重试一次，避免因服务端瞬时抖动导致签到失败
- **用户信息获取重试**：签到前获取余额信息的请求同样支持重试，防止网络波动影响签到流程
- 重试日志清晰标注 `[RETRY]`，便于排查

#### v1.6 - 插件一键注册新平台 + 多账号同一平台支持

- **插件自动注册新平台**：同步所有账号时，插件会自动更新 `PROVIDERS` GitHub Secret，将所有非内置平台的 `domain` 注册进去，签到脚本读取后即可路由到正确站点，无需手动修改任何 secret
- **修复新平台路由到 anyrouter 的 bug**：旧版 `ANYROUTER_ACCOUNT_*` secret 只包含 `cookies` 和 `api_user`，`config.py` 加载时 `provider` 默认为 `anyrouter`，导致新站点请求发到了 `https://anyrouter.top`。现在插件推送的 secret 值包含 `provider` 和 `domain` 字段，签到脚本会优先读取
- **签到脚本自动注册 provider**：即使 `PROVIDERS` secret 尚未更新，签到脚本也会读取账号中的 `domain` 字段，在运行时自动注册 provider，作为双重保险
- **修复多账号同一平台去重 bug**：旧版去重键仅为 `api_user`，不同平台若碰巧有相同 ID 会被错误合并。现改为 `(api_user, provider)` 组合键，同平台去重，不同平台保留
- **动态 provider tag 生成**：新增 `getProviderTag()` 函数，未知域名自动从 hostname 推导 tag（如 `computetoken.ai` → `COMPUTETOKEN`），不再输出 `UNKNOWN`
- `PROVIDER_DOMAINS` 和 `DOMAIN_TO_PROVIDER` 新增 `computetoken`（`https://computetoken.ai`）

### 2026-03-12

#### v1.5 - Cookie 提取与 api_user 解析修复

- **修复 Cookie 竞态条件**：重构 `syncOneAccount` 为两阶段：Phase 1 直接从浏览器 cookie jar 读取（无需打开 tab），Phase 2 仅在 jar 中找不到时才打开后台 tab。之前总是先打开 tab 再查 cookie，导致服务器 invalidate/rotate session，造成 0/5 同步失败
- **修复 api_user 解析失败**：Service Worker 的 `fetch()` 无法跨域发送 Cookie 头，导致 `/api/user/self` 请求 401。改为优先从 localStorage 读取 user id（new-api 前端缓存），零网络请求；回退到在页面上下文中执行同源 XHR
- **修复 tab 生命周期 bug**：`fetchApiUser` 调用前 tab 已被关闭并置空，导致 `tab?.id` 永远为 `undefined`。现在先调用 `fetchApiUser` 再关闭 tab
- **油猴脚本同步更新**：`fetchApiUser` 新增 localStorage 快速路径，在目标站点页面上直接读取缓存的 user id，无需发起 API 请求
- Chrome 扩展版本升至 v1.4.0

### 2026-03-11

#### v1.4 - 加密实现修复

- **修复 GitHub Secrets 加密 bug**：原先用 TweetNaCl 手动模拟 sealed box，nonce 由 `nacl.hash`（SHA-512）派生，而 GitHub 的 libsodium `crypto_box_seal` 使用 Blake2b 派生 nonce，二者不兼容导致 GitHub 无法解密推送的 secret。现改用 `libsodium-wrappers`，通过 `sodium.crypto_box_seal()` 实现正确的 sealed box 加密
- Chrome 扩展：引入 `libsodium.min.js` + `libsodium-wrappers.min.js`，替换 `tweetnacl.min.js`，manifest.json 添加 `wasm-unsafe-eval` CSP
- Tampermonkey：`@require` 改为 libsodium CDN 版本
- 导入 `ANYROUTER_ACCOUNTS` 时仅保留 `domain`，不再保留旧 `api_user`、`env_key_suffix` 或 `session`
- Chrome 扩展和 Tampermonkey 脚本同步时始终实时抓取浏览器中的最新 `session`，并重新调用 `/api/user/self` 解析当前 `api_user`

#### v1.3 - Secret 命名规范统一

- **统一 Secret 命名格式为 `{api_user}_{PROVIDER}`**：`api_user` 是各平台内部自增 ID，不同平台间可能重复，因此不能单独用 `api_user` 作为 secret 后缀，必须加上平台标识才能唯一区分
- Chrome 插件和 Tampermonkey 脚本：导入 ANYROUTER_ACCOUNTS 时所有账号（包括 anyrouter 本身）统一生成 `{api_user}_{PROVIDER}` 格式的 `env_key_suffix`
- `background.js` / Tampermonkey `syncOneAccount`：手动配置账号时，若未填写 `env_key_suffix`，在 `api_user` 自动解析成功后自动生成 `{api_user}_{PROVIDER}` 后缀，不再 fallback 为纯 `api_user`
- README 更新 Secret 命名规范说明，删除混用两种格式的示例

#### v1.2 - Tampermonkey 脚本 + 导入功能

- **Tampermonkey 油猴脚本**：新增 `anyrouter-cookie-updater.user.js`，功能与 Chrome 扩展对等，支持所有主流浏览器，通过 `GM_cookie` 读取 cookie，通过 `GM_xmlhttpRequest` 跨域调用 GitHub API，通过 `GM_registerMenuCommand` 注册油猴菜单命令，内置同款设置面板（列表/JSON 双模式）和日志查看器
- 自动同步支持基于页面加载的间隔检查（`GM_setValue` 记录上次同步时间）
- **从 ANYROUTER_ACCOUNTS 一键导入**：Chrome 扩展和 Tampermonkey 脚本均新增"📥 导入"按钮，粘贴原有 `ANYROUTER_ACCOUNTS` JSON（支持多行）后会按 provider 转换为 domain 列表，支持覆盖或按 domain 合并去重
- **UI 优化**：`cookie_name` 字段预填 `session`；JSON 模式空 textarea 不再报错可直接切换；日志按钮改为紫色，导入按钮为橙色，颜色层次更清晰

#### v1.1 - Chrome 扩展体验优化

- **双模式账号配置**：Chrome 扩展 AnyRouter Cookie Updater 现支持两种账号输入方式，可随时切换且数据互相同步：
  - **列表模式**：逐条填写，每个账号有独立的表单行，方便新增、删除和逐字段编辑
  - **JSON 模式**：批量粘贴 JSON 数组，适合一次性导入多账号，含实时语法校验
- **api_user 自动获取**：账号配置中 `api_user` 和 `env_key_suffix` 均变为可选字段；扩展在提取 cookie 后会自动调用 `/api/user/self` 接口解析用户 ID，最简配置只需填写 `domain`
- **扩展图标**：使用项目 `icon.png` 替换临时生成的占位图标

#### v1.0 - 初始版本

- **通知增强**：飞书/通知消息中每个账号显示所属平台名称和域名
- **多行 JSON 支持**：`ANYROUTER_ACCOUNTS` 和 `PROVIDERS` 支持多行 JSON，无需压缩为单行
- **ANYROUTER_ACCOUNT_* 独立账号管理**：参考 [autocheck-anyrouter](https://github.com/rakuyoMo/autocheck-anyrouter) 方案，支持通过前缀环境变量独立管理每个账号的 cookie
- **GitHub Actions 适配**：workflow 自动注入所有 `ANYROUTER_ACCOUNT_*` secrets 到环境变量
- **Chrome 扩展 AnyRouter Cookie Updater**：自动从浏览器提取 session cookie 并推送到 GitHub Actions Environment Secrets

---

## 免责声明

本脚本仅用于学习和研究目的，使用前请确保遵守相关网站的使用条款。

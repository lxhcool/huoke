# Huoke

面向外贸业务员的 AI 获客线索发现 Agent。

当前仓库已包含：

- `docs/`：方案设计文档
- `apps/web`：Next.js 前端工作台
- `apps/api`：FastAPI 后端 API

## 推荐技术栈

- 前端：`Next.js` + `TypeScript`
- 后端：`FastAPI`
- 数据库：`PostgreSQL`
- 缓存/任务：`Redis`
- 首版策略：先跑通 `搜索工作台 + 统一搜索 API + Agent 查询编排`，再接真实数据主档

## 目录结构

```text
.
├── apps
│   ├── api
│   └── web
├── docs
└── docker-compose.yml
```

## MVP 范围

首版先完成以下链路：

1. 业务员输入关键词、国家、来源和客户偏好
2. 后端创建 `search_job` 与多源子任务
3. 前端轮询任务状态和结果
4. 系统先返回首批结果，再逐步补充联系人和活跃度
5. 业务员可收藏或标记无效，反馈写回数据库

当前代码已切换为真实来源优先的任务流模式，不再自动注入演示结果。

- 默认可直接用本地 `SQLite` 启动
- 如果要切到正式环境，按 `apps/api/.env.example` 配置 `PostgreSQL`
- 已提供批量导入接口和业务员反馈接口，便于逐步接入真实数据
- 已提供任务流接口：`/api/search-jobs`、`/api/search-jobs/{job_id}`、`/api/search-jobs/{job_id}/results`
- `joinf_business` / `joinf_customs` / `linkedin_company` / `linkedin_contact` 任务已接入真实抓取骨架
- 推荐在前端「数据源账号管理」中按站点独立配置账号密码并点击「验证登录」
- 也支持脚本登录或 `.env` 方式作为兜底

## 本地开发

### 一键启动

```bash
make dev
```

说明：

- 自动创建 `apps/api/.venv`
- 自动安装 API 和 Web 依赖
- 自动执行演示数据初始化
- 自动启动 API 和 Web
- API 日志输出到 `.dev-api.log`

### 1. 启动 API

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

如果只是本地快速验证，也可以不创建 `.env`，系统会默认使用 `SQLite` 文件库。

### 1.1 批量导入真实数据

接口：`POST /api/imports/companies`

示例请求：

```json
{
  "companies": [
    {
      "standard_name": "Example GmbH",
      "country": "Germany",
      "industry": "Industrial Equipment",
      "keywords_text": "laser cutting,automation",
      "contacts": [
        {
          "full_name": "Alice Demo",
          "job_title": "Procurement Manager",
          "email": "alice@example.com",
          "priority_rank": 1
        }
      ],
      "customs_records": [
        {
          "subject_name": "Example GmbH",
          "hs_code": "845611",
          "trade_date": "2026-04-01",
          "trade_frequency": 5,
          "active_label": "最近 6 个月活跃"
        }
      ]
    }
  ]
}
```

### 1.2 记录业务员反馈

接口：`POST /api/feedback`

示例请求：

```json
{
  "company_id": 1,
  "action": "favorite",
  "query_text": "帮我找德国做激光切割设备的公司"
}
```

### 2. 启动 Web

```bash
cd apps/web
npm install
npm run dev
```

### 3. 访问地址

- Web：`http://localhost:4000`
- API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`

## 下一步开发顺序

1. 接入真实公司数据源
2. 完善 `company_master` 与 `contact_master` 字段
3. 打通海关映射规则
4. 增加收藏、导出、反馈闭环
5. 接入排序优化与 Agent 工具调用

## Joinf 抓取器骨架

当前已提供 Joinf 登录态抓取骨架，包含：

- 登录态保存
- 商业数据页面入口抓取
- 海关数据页面入口抓取
- 原始结果 JSON 落盘
- 运行时截图保存

### 运行方式

```bash
cd apps/api
source .venv/bin/activate
python -m app.scripts.joinf_capture login
python -m app.scripts.joinf_capture business --keyword "laser cutting" --country Germany
python -m app.scripts.joinf_capture customs --keyword "laser cutting" --country Germany
python -m app.scripts.linkedin_capture login
python -m app.scripts.linkedin_capture company --keyword "laser cutting" --country Germany
python -m app.scripts.linkedin_capture contact --keyword "laser cutting" --country Germany
```

### 前端验证登录（推荐）

1. 打开工作台页面 `http://localhost:4000`
2. 在左侧「数据源账号管理」分别填写各网站账号密码（仅保存在当前浏览器）
3. 对每个网站点击「验证登录」
   - 可填账号密码自动登录
   - 也可留空后手动在弹出的浏览器中登录（接口会等待约 4 分钟）
4. 验证成功后再点击「开始搜索」

后端接口：

- `GET /api/source-auth/providers`
- `POST /api/source-auth/{source_name}/verify`

### 环境变量（自动登录）

在 `apps/api/.env` 配置（可选兜底）：

```bash
JOINF_USERNAME=your_joinf_account
JOINF_PASSWORD=your_joinf_password
LINKEDIN_USERNAME=your_linkedin_account
LINKEDIN_PASSWORD=your_linkedin_password
```

### 运行结果

- 登录态：`apps/api/runtime/joinf/storage-state.json`
- 登录态：`apps/api/runtime/linkedin/storage-state.json`
- 原始数据：`apps/api/runtime/joinf/raw/`
- 原始数据：`apps/api/runtime/linkedin/raw/`
- 截图：`apps/api/runtime/joinf/screenshots/`
- 截图：`apps/api/runtime/linkedin/screenshots/`

说明：当前为抓取骨架版本，后续需要根据 `cloud.joinf.com` 实际页面结构补充稳定选择器和详情页字段提取逻辑。

补充说明：

- Joinf 入口策略已调整为「优先进入全球买家并填写定制信息」，如果页面未命中再回退旧的「数据营销 -> 商业/海关」路径。
- LinkedIn 若在当前网络环境被强制跳转到 `linkedin.cn`，系统会提示并中止；需切换到可访问 `linkedin.com` 的网络环境。
- 为降低页面变更影响，Joinf 任务支持“自动失败后人工导航抓取”兜底：
  - 点击查询后若自动步骤失败，系统会打开浏览器进入人工模式。
  - 你只需手动打开目标结果页（有表格数据的页面），系统检测到表格后会自动抓取并继续任务。

# 数据字段映射表 V1

## 1. 文档目的

本表用于定义 `Joinf 商业数据`、`Joinf 海关数据`、`LinkedIn` 原始字段，如何映射到系统内部的主档结构中。

当前系统内部核心对象为：

- `company_master`
- `contact_master`
- `customs_record`
- `company_contact_relation`
- `company_customs_relation`

## 2. 映射原则

- 页面原始字段先进入原始层，不直接覆盖主档
- 主档字段只保存标准化后的值
- 所有来源字段都需要保留来源 URL 与抓取时间
- 同一个字段可由多个来源补充，最终由置信度与优先级决定主档值

## 3. Joinf 商业数据 -> 系统字段

| 来源字段 | 系统表 | 系统字段 | 说明 |
|---|---|---|---|
| 公司名称 | `company_master` | `standard_name` | 若无标准名，先用原始名 |
| 国家/地区 | `company_master` | `country` | 做国家字典归一 |
| 城市 | `company_master` | `city` | 做城市归一 |
| 官网 URL | `company_master` | `website` | 原始官网链接 |
| 域名 | `company_master` | `domain` | 从官网提取或页面直接提供 |
| 行业 | `company_master` | `industry` | 用于搜索与标签 |
| 公司简介 | `company_master` | `description` | 用于推荐理由与搜索 |
| 员工规模 | `company_master` | `employee_size` | 当前系统待扩字段 |
| 成立时间 | `company_master` | `founded_year` | 当前系统待扩字段 |
| 活跃标签 | `company_master` | `activity_tags` | 当前系统待扩字段 |
| 采购关键词标签 | `company_master` | `procurement_tags` | 当前系统待扩字段 |
| 企业邮箱 | `contact_master` / `company_master` | `email` / `company_email` | 若无具体联系人，先挂企业级邮箱 |
| 联系电话 | `contact_master` / `company_master` | `phone` / `company_phone` | 同上 |
| 联系人姓名 | `contact_master` | `full_name` | 联系人主档核心字段 |
| 联系人职位 | `contact_master` | `job_title` | 职位标签归一 |
| 联系人邮箱 | `contact_master` | `email` | 优先企业邮箱 |
| 联系人电话 | `contact_master` | `phone` | 当前系统待扩字段 |
| 联系人 LinkedIn 链接 | `contact_master` | `linkedin_url` | 后续用于去重 |
| 来源页面 URL | `source_trace` | `source_url` | 建议新增来源追踪表 |
| 抓取时间 | `source_trace` | `fetched_at` | 审计用途 |

## 4. Joinf 海关数据 -> 系统字段

| 来源字段 | 系统表 | 系统字段 | 说明 |
|---|---|---|---|
| 海关主体名称 | `customs_record` | `subject_name` | 海关原始主体名 |
| 标准公司名称 | `company_master` | `standard_name` | 仅在可明确映射时使用 |
| 国家/地区 | `company_master` / `customs_record` | `country` | 作为辅助映射字段 |
| 贸易方向 | `customs_record` | `trade_direction` | import / export |
| HS Code | `customs_record` | `hs_code` | 核心字段 |
| 产品描述 | `customs_record` | `product_description` | 核心字段 |
| 最近交易时间 | `customs_record` | `trade_date` | 可存最近一条 |
| 交易频次 | `customs_record` | `trade_frequency` | 用于活跃判断 |
| 活跃标签 | `customs_record` | `active_label` | 例如最近 12 个月持续进口 |
| 高频产品标签 | `customs_record` | `high_frequency_tags` | 当前系统待扩字段 |
| 采购趋势标签 | `customs_record` | `trend_tags` | 当前系统待扩字段 |
| 来源页面 URL | `source_trace` | `source_url` | 审计用途 |
| 抓取时间 | `source_trace` | `fetched_at` | 审计用途 |

## 5. LinkedIn 公司数据 -> 系统字段

| 来源字段 | 系统表 | 系统字段 | 说明 |
|---|---|---|---|
| 公司名称 | `company_master` | `standard_name` | 参与公司去重 |
| 公司主页链接 | `company_master` | `linkedin_company_url` | 当前系统待扩字段 |
| 公司简介 | `company_master` | `description` | 可作为辅助补充 |
| 行业标签 | `company_master` | `industry` | 辅助修正行业 |
| 员工规模 | `company_master` | `employee_size` | 当前系统待扩字段 |
| 地区信息 | `company_master` | `country` / `city` | 作为辅助字段 |
| 官网 | `company_master` | `website` | 可补齐官网 |
| 关键岗位标签 | `company_master` | `org_role_tags` | 当前系统待扩字段 |
| 来源页面 URL | `source_trace` | `source_url` | 审计用途 |
| 抓取时间 | `source_trace` | `fetched_at` | 审计用途 |

## 6. LinkedIn 联系人数据 -> 系统字段

| 来源字段 | 系统表 | 系统字段 | 说明 |
|---|---|---|---|
| 联系人姓名 | `contact_master` | `full_name` | 联系人主档核心字段 |
| 职位 | `contact_master` | `job_title` | 用于识别采购相关角色 |
| 所属公司 | `company_contact_relation` / `company_master` | `company_id` | 需做映射 |
| 国家/地区 | `contact_master` | `country` | 当前系统待扩字段 |
| 个人主页链接 | `contact_master` | `linkedin_url` | 核心字段 |
| 团队角色标签 | `contact_master` | `role_tags` | 当前系统待扩字段 |
| 抓取时间 | `source_trace` | `fetched_at` | 审计用途 |

## 7. 建议新增的系统字段

为了更好承接增强版字段，建议后续在系统模型中新增以下字段：

### 7.1 `company_master`

- `employee_size`
- `founded_year`
- `company_phone`
- `company_email`
- `linkedin_company_url`
- `activity_tags`
- `procurement_tags`
- `org_role_tags`

### 7.2 `contact_master`

- `phone`
- `country`
- `role_tags`

### 7.3 `customs_record`

- `high_frequency_tags`
- `trend_tags`
- `country`

### 7.4 `source_trace`

建议单独新增来源追踪表，至少包含：

- `entity_type`
- `entity_id`
- `source_name`
- `source_url`
- `source_record_id`
- `fetched_at`
- `batch_id`

## 8. 当前开发建议

建议下一阶段按以下顺序落地：

1. 先补系统字段
2. 再写抓取结果入库映射器
3. 最后做主档合并与去重规则


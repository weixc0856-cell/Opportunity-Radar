# 页面变更监测（无 Feed 的官方来源）

`opportunity_radar/page_monitor.py` 处理"官方页面存在、但没有可用的 RSS/API"的来源。

它**不是**爬虫：

- 只检查 `config/page_watch.csv` 里显式列出的页面；
- 只抽取列表页上的**链接与标题**，不抓取文章正文；
- 不登录、不绕验证码、不伪装成浏览器 UA；
- 每个页面有最小检查间隔（小时），默认 6 小时。

## 它为什么存在

中国部委、政策发布页大多没有 Feed。把它们登记成"RSS 来源"会让审计出现一条永远不产出的记录。页面监测承认这条路径不同：**列表页 → 链接 → 原始文件**，只保存链接元数据。

## 配置

`config/page_watch.csv`：

| 字段 | 含义 |
|---|---|
| `watch_id` | 唯一 ID |
| `institution` / `name` | 机构与页面名 |
| `url` | 要监测的 HTTPS 页面 |
| `include_pattern` | 只保留匹配该正则的链接（匹配 **URL + 标题**） |
| `exclude_pattern` | 排除匹配的链接 |
| `min_links` | 低于该数量视为"页面结构变化" |
| `min_interval_hours` | 最小检查间隔，≥ 1 |
| `terms_url` | 该页面的条款入口（没有就留空） |
| `status` | `candidate` / `approved` / `blocked` / `retired` |
| `notes` | 实测事实与未决问题 |

`include_pattern` 强烈建议写死到详情页路径，否则导航栏、页脚、语言切换都会被当成"新条目"。例如国家统计局：

```
/sj/zxfb/20\d{2}\d{2}/t\d+_\d+\.html
```

## 安全与合规规则（代码强制）

1. **robots.txt 先行**：每次检查前读取 `robots.txt`，按最长匹配规则判断；`401/403/5xx` 视为"未获授权"，**不抓页面**。只有 404（没有规则）才继续。
2. **403/401/429 立即停止**：记为 `blocked`，不重试、不换 UA。
3. **低频**：未到 `min_interval_hours` 直接返回 `skipped_interval`，不发请求。
4. **结构变化不制造假新条目**：抽取到的链接少于 `min_links` 时，保留上一次指纹，只报告 `structure_changed`。否则页面改版后下一次会把所有条目都当"新"。
5. **同站限制**：只保留同一主机或父子域名的链接；站外链接丢弃。
6. **失败闭合**：任何异常状态都写入状态表，不静默跳过。

## 状态

`new_items` / `unchanged` / `skipped_interval` / `structure_changed` / `blocked` / `not_found` / `fetch_failed` / `robots_disallowed` / `not_approved`。

## 存储

使用 `OR_DB_PATH` 指向的 SQLite：

- `page_watch_state`：每个页面一行，保存指纹、条目数、最近检查时间、HTTP 状态、结果状态与错误；
- `page_watch_items`：首次见到的链接（`watch_id + item_url` 唯一），带标题、首次发现时间、来源页面 URL。

**保存的是"这个链接第一次出现在哪个页面、什么时候"，不是文章内容。** 追溯链条是：`page_watch_items.page_url` → 列表页 → `item_url` → 原始文件。

## 命令

```powershell
.\.venv\Scripts\python.exe -m opportunity_radar.page_monitor
.\.venv\Scripts\python.exe -m opportunity_radar.page_monitor --watch-id cn-stats-releases --json
```

## 当前页面（2026-10-23）

| watch_id | 页面 | 状态 | 实测 |
|---|---|---|---|
| `cn-stats-releases` | 国家统计局「最新发布」 | approved | HTTP 200；robots.txt 404（无规则）；include 后 15 条；首次运行记录 15 条，第二次因间隔限制 `skipped_interval` |
| `cn-gov-policy` | 中国政府网「最新政策」 | blocked | 列表由 JS 渲染，静态页面只有页脚链接；旧 pushinfo XML 与 `/zhengce/zuixin/home.htm` 均 404 |

**`cn-gov-policy` 的结论是"静态监测不可行"，不是"没有政策"。** 需要浏览器渲染能力才能接入，本轮不做。

## 接入新页面的步骤

1. 手工打开页面，确认它确实是**列表面**且链接指向原始文件/公告页；
2. 查看 `robots.txt` 是否允许；
3. 用 `--watch-id` 先跑一次，检查抽取到的链接是否都是业务条目（而不是导航）；
4. 写 `include_pattern` 收窄，再跑一次；
5. 确认标题与链接正确后，把 `status` 改为 `approved`，并在 `notes` 记录日期与观测结果。

## 未做

- 不渲染 JavaScript；
- 不解析正文、不判断文章是否重要、不进入简报；
- 不自动把页面条目转换成 `sources.csv` 的文章源。页面监测目前是**独立的观测工具**，与日报管线解耦。

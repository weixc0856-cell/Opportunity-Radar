# 正文获取（可选，逐源启用）

`opportunity_radar/fulltext.py` 为"Feed 只给标题+摘要、但原文页可访问"的来源提供正文。
它是**逐源 opt-in**，默认关闭：全部 43 行登记当前都是 `full_text_fetch=none`。

## 为什么需要

第一轮 E2E 的结论：七個官方/新闻来源全部是摘要级，A 通道停在 E1，E2 为 0。
要拿到 E2，只能拿到正文，而且必须经过复核——不能靠长度或模型评分自动授予。

## 启用方式（三步，缺一不可）

1. **条款核对**：确认该来源允许自动获取页面，并记录到 `terms_url` / `review_notes`。未读条款不要启用。
2. **试抓**：用下面的命令抓一篇，检查状态、容器与预览是否确实是正文，而不是导航或付费墙提示。
3. **登记**：把该行的 `full_text_fetch` 改为 `article_page`，并在 `review_notes` 记录试抓日期与结论。

> 改了 `full_text_fetch` **不会**提高证据等级。只有复核后把 `content_access_level` 改为 `full_text`，`content_basis()` 才允许 E2。两个字段分开，正是为了避免"抓到一段较长文本就自动升级"。

## 运行时的安全规则（代码强制）

| 规则 | 行为 |
|---|---|
| 只对声明 `article_page` 的来源抓取 | 其他来源只使用 Feed 文本 |
| 先读 robots.txt | 对本 UA 不允许则跳过，不发页面请求 |
| robots.txt 401/403/5xx | 视为未授权，跳过 |
| 页面 401/403/429 | 记为 `blocked`，不重试、不换身份 |
| 跨主机重定向 | 拒绝（登录页、付费墙常这样出现） |
| 正文过短（<200 字符） | `too_short`，保留 Feed 文本 |
| 付费墙标记 | `paywall_suspected`，保留 Feed 文本 |
| 单次运行上限 | 最多 20 篇，超出记录警告 |
| 失败 | 保留 Feed 摘要，不影响分析，不改变证据等级 |

抓到的正文替换 `article.summary`，原始 Feed 摘要保留在 `article.feed_summary`，`content_source` 记为 `article_page`。

## 试抓命令

```powershell
.\.venv\Scripts\python.exe -m opportunity_radar.fulltext --url "https://www.federalreserve.gov/newsevents/pressreleases/enforcement20261016a.htm"
```

输出：状态、字符数、容器（`article` / `main` / `content-div` / `body`）与前 160 字预览。只读，不写数据库。

2026-10-23 试抓结果：

| 页面 | 结果 | 容器 | 字符 | 备注 |
|---|---|---|---|---|
| Fed 新闻稿 | fetched | content-div | 904 | 开头有面包屑，正文完整 |
| BBC 新闻 | fetched | article | 7,684 | 结构与正文良好 |
| ONS 发布页 | fetched | — | ~3,000 | 页面较短 |
| NVIDIA 新闻稿 | fetched | — | ~5,600 | 可用 |
| NYT 文章 | 未抓 | — | — | 非浏览器客户端被拒，未绕过 |

## 复核清单（改为 `content_access_level=full_text` 之前）

- [ ] 同一来源抽 2–3 篇不同长度的文章，确认提取结果都是完整正文；
- [ ] 确认没有把导航、推荐位或"订阅继续"混进正文；
- [ ] 确认页面发布日期与 Feed 条目一致；
- [ ] 条款允许保存与摘要，并在 `review_notes` 写明依据；
- [ ] 复核后在 `review_notes` 记录日期与结论。

任何一项不满足，保持 `content_access_level=excerpt`，E2 不会出现——这是正确行为。

## 已知局限

- 用正则提取，没有 HTML 解析依赖：嵌套结构复杂的页面可能落到 `body`，带导航噪声；
- 不执行 JavaScript，JS 渲染的页面会 `too_short`；
- 不处理付费墙，也不尝试绕过；
- 只抓单页，不跟随分页；
- 没有正文缓存：同一 URL 再次分析时会重新抓取（受 20 篇上限约束）。

## 当前状态

- 43 行登记全部 `full_text_fetch=none`；没有任何来源被启用正文抓取。
- 因此现有跑批行为与第一轮完全一致；该能力只通过试抓命令验证过。

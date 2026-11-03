# 每日内容本地归档

## 目录

```text
data/
  opportunity_radar.sqlite3       # 当前可查询的结构化数据
reports/
  latest-digest.html              # 最新 HTML 报告
  latest-digest.txt               # 最新文本报告
  archive/
    YYYY/MM/DD/
      YYYY-MM-DD-HHMMSS.html      # 单次运行 HTML
      YYYY-MM-DD-HHMMSS.txt       # 单次运行 TXT
      YYYY-MM-DD-HHMMSS.items.json      # 该次结构化分析快照
      YYYY-MM-DD-HHMMSS.manifest.json   # 运行 ID、哈希、统计和文件清单
```

## 数据职责
- SQLite 是查询和更新用的结构化主存储。
- 每次运行目录是便于阅读、导出、备份和复盘的不可覆盖快照。
- `latest-digest.*` 只是方便查看的快捷副本，会被下一次运行覆盖。
- 不默认保存第三方文章全文；归档包含分析输出、证据元数据、原文 URL 和报告。
- `data/` 与 `reports/` 被 `.gitignore` 排除。备份时单独复制它们，公开发布时不要把个人数据或凭据带进仓库。

## 建议备份
每周关闭正在运行的日报任务后，复制 `data/opportunity_radar.sqlite3` 和 `reports/archive/` 到一个不公开的备份位置。若以后数据量增长，可再增加保留策略和自动备份任务。

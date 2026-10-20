# Source approval policy

All sources start disabled. Before enabling a source, record official owner, canonical URL, documented RSS/API method and terms, robots.txt result and review date where relevant, allowed access frequency, allowed storage/analysis/internal summary uses, retention limits and attribution requirements.

`robots.txt` is not complete legal authorization. Public visibility does not automatically license bulk collection, storage or redistribution. Do not bypass authentication, paywalls, CAPTCHAs, rate limits or technical access controls. If terms are unclear, keep disabled. Suspend a source if permissions change or access is blocked. Email should contain concise summaries and links, not full article copies.

每个已批准来源必须在 `config/sources.csv` 中配置准确的 `freshrss_feed_id`。程序只处理映射到已批准来源的文章；无法映射的 feed 默认跳过。

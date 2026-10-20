# Source approval policy

All repository sources start disabled, and local FreshRSS feed IDs are blank because they are installation-specific. Before enabling a source, record the official owner, canonical domain, actual feed provider (if different), documented RSS/API method, owner and provider terms, review date, allowed access frequency, allowed storage/analysis/internal summary uses, retention limits and attribution requirements. Use `python -m opportunity_radar.source_audit` to check metadata completeness. Optional URL checks only confirm reachability; they do not confirm authenticity, accuracy or permission.

`robots.txt` is not complete legal authorization. Public visibility does not automatically license bulk collection, storage or redistribution. Do not bypass authentication, paywalls, CAPTCHAs, rate limits or technical access controls. If terms are unclear, keep disabled. Suspend a source if permissions change or access is blocked. Email should contain concise summaries and links, not full article copies.

每个已批准来源必须在 `config/sources.csv` 中配置准确的 `freshrss_feed_id`。程序只处理映射到已批准来源的文章；无法映射的 feed 默认跳过。

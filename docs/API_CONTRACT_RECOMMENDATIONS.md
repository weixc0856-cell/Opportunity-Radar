# Opportunity Radar API 契约与改进建议

## 1. 当前接口

| Method | Path | 当前用途 |
|---|---|---|
| GET | `/api/status` | 运行、模型、来源、收件人、报告状态 |
| GET | `/api/sources` | 来源列表与字段定义 |
| POST | `/api/sources/save` | 保存完整来源列表 |
| GET | `/api/freshrss-feeds` | 从本机 FreshRSS 读取 Feed |
| GET | `/api/recipients` | 收件人列表 |
| POST | `/api/recipients/save` | 保存收件人列表 |
| POST | `/api/email/test` | 向配置收件人发送测试邮件 |
| POST | `/api/run` | 启动一次日报 |
| POST | `/api/schedule` | 在 Windows 注册每日任务 |
| GET | `/api/logs` | 查看日志尾部 |
| GET | `/report` | 查看最新 HTML 报告 |
| GET | `/api/audit` | 来源登记审计 |
| POST | `/api/source-check` | 来源登记审计，可选 URL 可达性检查 |

## 2. 统一响应结构（建议迁移）

成功：
```json
{
  "ok": true,
  "data": {},
  "request_id": "local-request-id"
}
```

失败：
```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "来源未通过审核",
    "details": [
      {
        "field": "freshrss_feed_id",
        "message": "启用来源必须填写实际 Feed ID"
      }
    ]
  },
  "request_id": "local-request-id"
}
```

## 3. 错误码建议

- `CONFIG_MISSING`
- `VALIDATION_FAILED`
- `SOURCE_AUDIT_FAILED`
- `FRESHRSS_UNAVAILABLE`
- `LLM_UNAVAILABLE`
- `LLM_INVALID_OUTPUT`
- `RUN_ALREADY_ACTIVE`
- `RUN_START_FAILED`
- `SMTP_AUTH_FAILED`
- `SMTP_CONNECTION_FAILED`
- `EMAIL_PARTIAL_FAILURE`
- `SCHEDULE_REGISTRATION_FAILED`
- `NOT_FOUND`
- `REQUEST_TOO_LARGE`
- `LOCAL_ACCESS_ONLY`

## 4. 邮件接口建议

`POST /api/email/test` 应返回每个地址的结果，不应只返回整体成功或失败：
```json
{
  "ok": true,
  "data": {
    "attempted": 2,
    "succeeded": 1,
    "failed": 1,
    "recipients": [
      {"address": "test1@example.com", "status": "submitted"},
      {"address": "test2@example.com", "status": "failed", "error_code": "SMTP_RECIPIENT_REJECTED"}
    ]
  }
}
```
`submitted` 只代表 SMTP 服务接受提交，不代表收件箱最终送达。

## 5. 运行接口建议

`POST /api/run` 返回持久化 `run_id`，而不只返回 OS PID：
```json
{
  "ok": true,
  "data": {
    "run_id": "run-20261020-080000",
    "status": "queued"
  }
}
```

建议新增：
- `GET /api/runs?limit=50`
- `GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/cancel`（若取消语义可安全实现）
- `GET /api/schedule`
- `DELETE /api/schedule`

状态枚举建议：`queued`、`running`、`succeeded`、`partial_failed`、`failed`、`cancelled`、`skipped_no_new_content`。

## 6. 输入校验与安全

- 所有字段明确类型、最大长度和允许值。
- 对未知字段返回验证错误或明确忽略，不默默写入。
- 任何写请求都执行本地 Host/Origin 校验。
- 请求体大小有限制；日志接口有固定最大输出。
- 不向前端返回 SMTP 密码、Fever API Key、LLM API Key。
- 错误响应不回传 traceback 或完整秘密配置。
- 所有 API 在本地单用户模式下也应有契约测试。

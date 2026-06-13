<!-- # truth-monitor extension -->

# Truth Monitor 使用说明

## 模块说明

- `app/adapters/truth_fetcher.py`：请求 Truth Social 公开 API 并标准化帖子字段。
- `app/adapters/truth_dedup.py`：使用 Redis `truth_seen_ids` 集合做 post_id 去重。
- `app/adapters/truth_downloader.py`：并发下载帖子媒体到 `data/media/{YYYY-MM-DD}/{post_id}/`。
- `storage/db.py`：维护 `truth_posts` SQLite 表和待注入记录查询。
- `app/adapters/truth_intake_bridge.py`：把未注入的 `truth_posts` 转成 `SourceReviewItem`，进入 source review queue。
- `app/notifier/telegram.py`：向 Telegram 发送新帖通知，token 为空时静默跳过。
- `app/jobs/truth_monitor_job.py`：串联 fetch、dedup、download、save、notify、intake 注入。
- `app/jobs/truth_scheduler.py`：使用 APScheduler 每 15 分钟运行一次 monitor job。

额外辅助文件：

- `scripts/truth_dryrun.py`：本地 mock/live dry-run 验证工具。
- `deploy/truth-monitor.service`：systemd 服务模板。

## 快速启动

1. 配置 `.env`

```text
TRUTH_ACCOUNT_ID=107780257626128497
REDIS_URL=redis://localhost:6379/0
MEDIA_DIR=./data/media
DEFAULT_WORKSPACE_ID=default
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
HTTP_PROXY=
```

2. 启动 Redis

```bash
redis-server
```

3. 运行 mock dry-run 验证

```bash
python scripts/truth_dryrun.py --mock
```

4. 运行 live dry-run 验证网络和 API 是否通

```bash
python scripts/truth_dryrun.py --live
```

5. 启动调度器

```bash
python -m app.jobs.truth_scheduler
```

6. systemd 部署

先按实际项目路径和 venv Python 路径编辑 `deploy/truth-monitor.service`：

```bash
sudo cp deploy/truth-monitor.service /etc/systemd/system/truth-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable truth-monitor
sudo systemctl start truth-monitor
sudo systemctl status truth-monitor
```

## 数据流说明

Truth monitor 每 15 分钟读取 `@realDonaldTrump` 的公开 Truth Social API 返回，清洗 HTML 得到纯文本，使用 Redis 去重，下载媒体文件，把结构化数据写入 `truth_posts`，可选发送 Telegram 通知，然后通过 intake bridge 转成 `SourceReviewItem`。后续仍进入已有的 source review queue，由人工审核后再进入 evidence、brief、video 和 platform package 流程。

## 注意事项

- Truth Social API 无官方授权，仅用于个人研究和内部验证；生产使用前需要自行确认网络访问、服务条款和合规风险。
- 建议配置 `HTTP_PROXY` 应对网络限制。
- Telegram token 可选，为空会自动跳过通知，不会报错。
- 注入后的内容仍是 `human_status=pending`，不会自动绕过人工审核、fact-check gate 或发布前人工确认。
- 系统仍不自动发布到 B 站、小红书、抖音、YouTube 或任何平台。

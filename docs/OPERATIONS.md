# ProofDemo V1 运维指南

## 支持的部署形态

V1 是本地模块化单体：使用 CLI 运行演示工作流，提供可选的 FastAPI 健康检查接口，并使用 Playwright Chromium 和本地 FFmpeg。它不包含数据库、队列、后台工作进程、用户认证、云产物存储或托管式多租户控制平面。只有实测工作负载表明确有需要时，才应增加这些能力。

## 生产配置

使用隔离的 Python 环境，并在部署系统中固定锁文件或约束。设置：

```text
PROOFDEMO_ENVIRONMENT=production
PROOFDEMO_API_HOST=127.0.0.1
PROOFDEMO_API_PORT=8000
PROOFDEMO_FRONTEND_ORIGIN=https://your-frontend.example
```

在持续维护的反向代理处终止 TLS。生产环境拒绝非 HTTPS 或通配符前端源站，禁用 API 文档，并发送 HSTS、CSP 及其他防御性响应头。提供方密钥应保留为进程环境中的秘密；在部署环境中绝不能将其写入 `.env`、命令历史、规范或产物。

## 发布流程

1. 运行 `proofdemo benchmark --output artifacts/benchmark_report.json`。
2. 运行 pytest、Ruff 格式/检查、mypy、schema 导出漂移检查和前端生产构建。
3. 运行 `python -m pip_audit --skip-editable` 和 `npm --prefix frontend audit --omit=dev`。
4. 执行真实 Todo 的 `run` 与 `replay` 验收，并验证两份清单。
5. 检查 diff 中是否包含密钥和生成产物。
6. 合并可审查的 PR；只给经过验证的合并提交打标签。

CI 使用 Chromium 和 FFmpeg 执行同样的自动化门禁。

## 产物处理与保留

产物目录可能包含应用截图、日志、下载文件和视频。应将其存储在受访问控制的加密存储中。V1 不提供自动保留或删除服务：运维人员必须定义保留期限，通过经批准且可恢复的流程移除过期目录，并轮换任何疑似出现在录制中的密钥。保留视频时一并保留源配方和清单，以便继续检查来源。

只备份策略要求保留的产物。应通过应用代码运行 `ArtifactWriter.verify`，或针对副本执行重放预检来测试恢复。有效哈希不能替代访问控制。

## 事件响应

停止正在进行的运行，保留相关清单/日志，隔离受影响产物，并撤销可能暴露的提供方或应用凭据。确定泄露是否发生在浏览器内容、诊断信息、下载文件或视频中。按照 `SECURITY.md` 私密报告安全问题。只有在完成修复并通过全部发布门禁验证后才能恢复运行。

## 容量与失败语义

运行目录位于本地，每次 CLI 调用都是一个前台工作流。只有在测量 CPU、磁盘、浏览器内存和 FFmpeg 耗时后，才通过隔离进程扩展。并发运行之间不得共享产物目录。`FAILED` 表示确定性的预期结果失败；`BLOCKED` 表示外部或运行时前置条件阻止了有意义的完成。绝不能通过重写结果来重试。

# ProofDemo 发布清单

每个 V1 候选版本都应使用此清单。记录实际命令和结果；不要根据更早阶段或另一台机器的结果推断通过。

## 自动化门禁

- [ ] `python scripts/export_schema.py` 执行后，已提交的 schema 保持不变。
- [ ] `proofdemo benchmark --output ...` 报告 `PASSED`，且三项指标均等于 `1.0`。
- [ ] `python -m pytest` 通过，其中包括环境中可用的 Chromium/FFmpeg 集成测试。
- [ ] `ruff format --check .` 和 `ruff check .` 通过。
- [ ] `mypy backend/src` 通过。
- [ ] `npm --prefix frontend run build` 通过。
- [ ] `python -m pip_audit --skip-editable` 和 `npm --prefix frontend audit --omit=dev` 均未报告已知漏洞。

## 真实验收

- [ ] 启动仓库内置 Todo fixture，并使用真实 Playwright Chromium 和 FFmpeg 运行 `examples/demo_spec.json`。
- [ ] 使用源产物重放生成的配方。
- [ ] 两次运行均为 `PASSED`；两份清单均验证通过；重放预检兼容；UI 变化状态为 `UNCHANGED`。
- [ ] 两个最终视频均探测为 H.264/yuv420p、1920x1080、30 fps。

## 安全与仓库审查

- [ ] 审查 diff 和依赖公告。
- [ ] 确认没有密钥、`.env`、浏览器状态或生成的运行产物被跟踪。
- [ ] 确认 `SECURITY.md`、威胁模型和运维指南仍准确描述已交付行为及剩余风险。
- [ ] 合并可审查的 PR，并且只给经过验证的合并提交打标签。

首个 V1 验证记录保存在 `docs/CURRENT_STAGE.md`；后续发布记录应保存在发布 PR 或发布说明中。

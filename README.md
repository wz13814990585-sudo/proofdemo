# ProofDemo

ProofDemo 是一个经过验证的产品演示系统。它的长期目标是把 Web 应用 URL 和自然语言意图转换为完成度高、可重放的演示，并让其中的重要声明都有可观察证据支持。

产品流程为：

```text
Intent -> Plan -> Execute -> Verify -> Capture -> Render
```

本仓库完成了 **Engine V1**、**Stage 11 本地产品工作台**和 **Stage 12 有证据约束的只读探索**：用户可从 UI 提交 URL 与目标，观察页面探索和执行、审查 DemoSpec/证据并获取已验证视频。探索只覆盖同源、可通过安全 GET 直接访问的页面；不是能登录、点击探索动态流程或理解任意陌生站点的通用 Browser Agent，也不是托管 SaaS。准确范围请参阅[当前阶段](docs/CURRENT_STAGE.md)。

## 前置要求

- Python 3.11 或更高版本
- Node.js 20.19 或更高版本
- npm 10 或更高版本
- 支持 H.264 编码的 FFmpeg 和 FFprobe

## 后端设置

创建隔离的 Python 环境，并安装项目及开发工具：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m playwright install chromium
cp .env.example .env
```

确定性管线不需要 API 密钥。若要使用可选规划器，请在环境中设置 `OPENAI_API_KEY`，并通过 `PROOFDEMO_OPENAI_MODEL` 或 `--model` 选择一个明确的模型；ProofDemo 不会替你选择会浮动变化的默认模型。

按需启用旁白还需要明确设置 `PROOFDEMO_OPENAI_TTS_MODEL` 和 `PROOFDEMO_OPENAI_TTS_VOICE`（或对应的 CLI 参数）。语音提供方只会接收已经批准的旁白文本。适配器使用的 WAV 语音端点记录在 [OpenAI 文本转语音指南](https://developers.openai.com/api/docs/guides/text-to-speech)中。

启动 API：

```bash
proofdemo-api
```

API 运行在 `http://127.0.0.1:8000`。本地任务保存在 `PROOFDEMO_JOB_ROOT`（默认 `artifacts/jobs`）。任务写入请求要求 `X-ProofDemo-Client: studio`，且浏览器请求的 Origin 必须与配置的前端源站一致；这只是防跨站请求边界，不是用户认证。不要把 API 直接暴露到公网。可通过以下命令验证：

```bash
curl http://127.0.0.1:8000/health
```

开发环境可在 `http://127.0.0.1:8000/docs` 访问交互式 API 文档。当 `PROOFDEMO_ENVIRONMENT=production` 时，该文档会被禁用。

## 前端设置

在第二个终端中运行：

```bash
npm --prefix frontend install
cp frontend/.env.example frontend/.env.local
npm --prefix frontend run dev
```

打开 `http://127.0.0.1:5173`。前端可输入产品 URL、演示目标、受众、语言和时长，点击“生成演示”，查看只读探索页面/控件与锚定覆盖、规划后的 DemoSpec、实时浏览器截图与操作事件、逐场景验证，以及仅在验证通过后可播放/下载的视频。具名高风险操作会停在单独审批态，凭据填充会被阻止。可在 `frontend/.env.local` 中设置 `VITE_API_BASE_URL`，覆盖默认 API URL。

工作台需要明确配置 `PROOFDEMO_OPENAI_MODEL` 和进程环境中的 `OPENAI_API_KEY`；缺少配置会显示 `BLOCKED`。它先在全新无凭据的 Chromium 会话中观察最多 5 个同源页面，再让模型仅从已观察的安全链接中建议下一页，并以版本化报告约束 DemoSpec。导航必须指向实际访问的页面，点击/填充必须精确匹配该页已观察的唯一控件；否则在执行前阻止。探索不提交表单、不点击、不访问跨源资源，并阻止非 GET 请求及重定向；这无法保证目标站点的 GET 端点本身无副作用。不要对敏感或未获授权站点运行。真实 Chromium/FFmpeg 验收覆盖两个本地应用，模型适配器仅用假客户端测试，尚无真实模型对任意站点成功率的证据。前端语言选择会传给规划器，但当前自动视频仍是基础 FFmpeg 合成；字幕、自动缩放和精美编辑尚未实现。

## 运行确定性示例

若要根据目标创建候选 DemoSpec，但不启动浏览器：

```bash
proofdemo plan https://app.example.test/ \
  --goal "Create a launch task" \
  --model YOUR_EXPLICIT_MODEL \
  --output candidate.json
```

CLI 的 `plan` 与 `run` 仍是两条显式命令，必须在运行前审查候选；CLI `plan` 不执行 Stage 12 探索。工作台的“生成演示”则会对证据锚定且安全评估为 `ALLOWED` 的计划继续执行；具名风险操作要求在 UI 中重新审核并批准。模型调用不使用工具，也不持久化对话；探索的逐页候选选择和最终 DemoSpec 是分开的有界结构化输出请求，模型不能直接操控浏览器。适配器使用的提供方机制请参阅 [OpenAI 结构化输出指南](https://developers.openai.com/api/docs/guides/structured-outputs)。

对于仓库内置的确定性示例，请在一个终端中启动独立的 Todo fixture：

```bash
python scripts/serve_todo_app.py
```

然后在另一个终端中执行内置 DemoSpec：

```bash
proofdemo run examples/demo_spec.json --artifacts artifacts/todo-demo
```

任何浏览器启动前，ProofDemo 都会写入 `safety_assessment.json`。类似凭据的填充操作始终会被阻止。具名的破坏性、金融、账户或生产环境操作必须通过 `--allow-risky-actions` 获得当次命令的重新批准；重放和修复不会继承此前批准。

若要在同一次运行成功验证后添加 AI 语音：

```bash
proofdemo run examples/demo_spec.json \
  --artifacts artifacts/todo-demo \
  --narrate \
  --tts-model YOUR_EXPLICIT_TTS_MODEL \
  --voice YOUR_EXPLICIT_VOICE
```

仅配置凭据不会自动启用旁白；必须提供 `--narrate`。第一条语音提示会声明该声音由 AI 生成。

每次成功运行还会写入 `demo_recipe.json`。可将其重放到新的产物目录：

```bash
proofdemo replay artifacts/todo-demo/demo_recipe.json \
  --artifacts artifacts/todo-demo-replay
```

浏览器启动前，`replay_preflight.json` 会记录配方/源运行的来源及每项兼容性问题。重放旁白仍需通过相同的 `--narrate`、`--tts-model` 和 `--voice` 参数按需启用。

如果源 `execution_report.json` 与配方位于同一目录，重放还会验证配方中记录的哈希，并写入 `ui_change_report.json`。使用 `--baseline-artifacts PATH` 可选择其他基线目录。显式指定的基线缺失或无效时，流程会在浏览器执行前停止；不带本地基线证据的可移植配方仍可重放，但变化状态为 `NOT_EVALUATED`。

对于结果为 `CHANGED` 的重放，可以提出一个有界的场景修复，但不执行它：

```bash
proofdemo propose-repair artifacts/todo-demo/demo_recipe.json \
  --change-artifacts artifacts/todo-demo-changed \
  --scene create_task \
  --hint "The submit button is now named Create task" \
  --model YOUR_EXPLICIT_MODEL \
  --output repair-candidate.json
```

审核候选结果后，再明确批准执行：

```bash
proofdemo apply-repair artifacts/todo-demo/demo_recipe.json repair-candidate.json \
  --change-artifacts artifacts/todo-demo-changed \
  --baseline-artifacts artifacts/todo-demo \
  --artifacts artifacts/todo-demo-repaired
```

完整通过验证的修复会写入 `partial_render.json` 和 `demo-repaired.mp4`。未变化场景的时间范围来自基线视频；只有被诊断的场景使用新录制素材。

一次成功的 Stage 4 运行会以 `0` 退出，依次从 `EXECUTED` 转换到 `PASSED`，并写入 `execution_report.json`、`trace.jsonl`、`browser.log.jsonl`、`browser.webm`、`timeline.json`、`demo.mp4`、`artifact_manifest.json`、请求的截图以及关联证据截图。最终 MP4 为 1920×1080、30 fps 的 H.264/yuv420p。`EXECUTED` 始终只表示浏览器操作已完成；只有确定性验证器可以产生 `PASSED`，并且只有经过验证且完整性检查通过的运行才能被合成。

成功运行还会写入 `demo_recipe.json`，其中嵌入规范化 DemoSpec 及其指纹、固定执行 profile、schema 要求，以及源执行报告和最终视频的哈希。

按需启用旁白的运行还会写入 `narration.json`、每场景一个 PCM WAV，以及包含 H.264 视频和 AAC 音频的 `demo-narrated.mp4`。每条提示都会引用一个已通过断言，并保留准确的已验证场景边界。

CLI 对操作级 `FAILED` 结果使用退出码 `1`；对被阻塞的浏览器基础设施或产物输出使用 `2`；对无效输入规范使用 `64`。

## 验证

激活 Python 环境并安装前端依赖后，运行：

```bash
proofdemo benchmark --output artifacts/benchmark_report.json
python -m pytest
ruff format --check .
ruff check .
mypy backend/src
npm --prefix frontend run build
```

修改领域模型后导出共享 DemoSpec schema：

```bash
python scripts/export_schema.py
```

如果 `shared/schemas/demo_spec.schema.json` 与权威 Pydantic 模型不一致，测试会失败。

离线基准通过应用服务覆盖验证成功、断言失败、操作失败和基础设施阻塞。V1 要求这个固定测试集上的预期终态结果、证据覆盖率和轨迹完整性全部达到满分；这是发布门禁，并不代表对任意网站或提供方质量的声明。

## 领域边界

- DemoSpec `1.2` 为 Scene、Action 和 Assertion 使用稳定 ID，并要求每个场景至少包含一项断言。
- `source_url` 定义允许访问的源站；每个 `goto` 都必须停留在该源站。
- `pause` 是演示延时，不是页面就绪检查。
- 字面填充值只能是非敏感演示数据。
- 浏览器适配器会在导航前和重定向后强制执行 DemoSpec 源站约束。
- 确定性断言覆盖元素可见性、文本包含、精确规范化 URL、已完成下载，以及一个声明的 JSON 应用状态键。
- `EXECUTED` 表示操作已完成，并不表示断言已通过。
- `PASSED` 要求每个场景的所有断言都带有结构化证据并通过。
- 采集失败会变成显式产物警告和轨迹事件；不会改写确定性断言结果。
- 产物清单会为该运行的所有其他产物记录相对路径、媒体类型、字节数、SHA-256 摘要和稳定关联 ID。
- 时间线策略由项目掌控；FFmpeg 只是用于探测、缩放、加黑边和编码的窄适配器。
- 规划器只能提出 DemoSpec 候选。ProofDemo 会重新验证候选、保持请求的源站，并要求单独、明确地执行 run 命令。
- 旁白只使用根据已通过断言类型选择的、由项目定义的短句。TTS 可以合成这些短句，但不能创作或扩展声明。
- 在有界语速策略下无法放入所属场景的语音会被拒绝；不会被截断、移动，也不能覆盖另一个场景。
- 配方是可移植输入，不是可信执行授权。重放会先验证规范指纹、版本、schema 和执行 profile，再委托给同一确定性管线并创建新的运行 ID。
- UI 变化检测根据稳定的操作/断言 ID，将结构化观察与已验证基线比较。它会报告变化类别，但不能改写选择器、断言、运行状态或素材。
- 修复只能替换一个场景中已诊断的现有 click/fill 操作或 element/text 断言的类型化目标。应用已审核建议后，会重新运行完整 DemoSpec；只有状态为 `PASSED` 后才能进行局部渲染。
- 规范最多包含 50 个场景；每场景最多 100 个操作和 100 个断言；操作和断言总数分别最多 500 个；声明的暂停总时长最多五分钟。
- 安全评估是确定性的，并且先于浏览器构建。每次实际执行的产物清单都包含其决策和任何明确批准。

## 仓库结构

```text
backend/src/proofdemo/  API, planning/execution/verification/media, and adapters
frontend/               React and TypeScript frontend
shared/schemas/         generated cross-runtime contracts
examples/               valid inputs and the deterministic Todo fixture
scripts/                deterministic developer utilities
tests/                  API and domain tests
docs/                   product, architecture, roadmap, and stage scope
```

## 项目文档

- [产品规格](docs/PROJECT_SPEC.md)
- [架构](docs/ARCHITECTURE.md)
- [路线图](docs/ROADMAP.md)
- [当前阶段](docs/CURRENT_STAGE.md)
- [威胁模型](docs/THREAT_MODEL.md)
- [运维指南](docs/OPERATIONS.md)
- [发布清单](docs/RELEASE_CHECKLIST.md)
- [安全策略](SECURITY.md)

## 安全

绝不能提交凭据，也不能将其放入 DemoIntent 或 DemoSpec 文件。`.env` 已被忽略；`.env.example` 只记录非秘密配置。V1 只接受非敏感字面填充数据，将导航限制在单一源站，并且不注入浏览器凭据。应用状态断言只能读取一个经过验证的顶层键，不能执行规范提供的 JavaScript。操作轨迹载荷会省略填充值，浏览器诊断文本会在持久化前进行有界清理和脱敏。提供方适配器只从环境读取凭据，绝不会将其存入规划器输入、候选结果、轨迹、旁白文本或产物。TTS 只接收非敏感、基于证据的固定短句，产物元数据会记录 AI 语音声明。配方不包含环境快照、Cookie、存储状态或凭据。安全筛查有意采用保守策略，但无法推断误导性或不透明目标标签背后的真实效果；仍然需要人工审查 DemoSpec。

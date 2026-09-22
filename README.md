# ProofDemo

[中文](#中文) · [English](#english)

ProofDemo turns a web-product workflow into a verified, replayable demo. It plans a typed `DemoSpec`, executes it in Chromium, checks deterministic assertions, preserves evidence, and renders video only after verification succeeds.

```text
Intent -> Explore -> Plan -> Execute -> Verify -> Capture -> Render
```

---

## 中文

### 项目简介

ProofDemo 是一个经过验证的产品演示系统。用户可以在本地工作台输入产品 URL 和演示目标，查看只读探索、规划、浏览器执行和验证过程，并在成功后获得可播放的视频。

当前仓库包含 Engine V1、本地产品工作台、有证据约束的同源只读探索，以及基于已验证轨迹的视频润色。它不是通用浏览器智能体，也不是托管 SaaS。准确范围参阅[当前阶段](docs/CURRENT_STAGE.md)。

### 已验证的本地成功案例

仓库保留两个完全本地、无需模型 API 的可重复案例：

| 案例 | 结构 | 验证内容 | DemoSpec |
| --- | --- | --- | --- |
| Todo | 单页应用 | 填写并创建任务、列表文本、URL、下载、应用状态 | [`examples/demo_spec.json`](examples/demo_spec.json) |
| Notes | 两页应用 | 同源页面导航、填写并发布笔记、结果文本和 URL | [`examples/notes_demo_spec.json`](examples/notes_demo_spec.json) |

自动化验收会让这两个站点经过真实 Chromium、确定性断言、录制、FFmpeg 合成与视频润色。它们是本地产品流程证据，不代表 ProofDemo 对任意网站都能成功。

#### 案例一：Todo

终端 1：

```bash
source .venv/bin/activate
python scripts/serve_todo_app.py
```

终端 2：

```bash
source .venv/bin/activate
proofdemo run examples/demo_spec.json --artifacts artifacts/todo-demo
```

#### 案例二：Notes

终端 1：

```bash
source .venv/bin/activate
python -m http.server 4174 --bind 127.0.0.1 --directory examples/notes_app
```

终端 2：

```bash
source .venv/bin/activate
proofdemo run examples/notes_demo_spec.json \
  --artifacts artifacts/notes-demo \
  --allow-risky-actions
```

Notes 中的 `Publish note` 会被保守的安全规则识别为具名发布操作，因此 CLI 要求本次运行显式批准。批准不会被重放或后续运行继承。

### 环境要求

- Python 3.11 或更高版本
- Node.js 20.19 或更高版本
- npm 10 或更高版本
- 支持 H.264 的 FFmpeg 和 FFprobe

### 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m playwright install chromium
cp .env.example .env

npm --prefix frontend install
cp frontend/.env.example frontend/.env.local
```

### 启动本地工作台

确定性 CLI 案例不需要模型密钥。工作台的自然语言规划需要显式配置一个提供方。

DeepSeek 示例（密钥只留在当前终端，不要写进仓库或聊天）：

```bash
export PROOFDEMO_PLANNER_PROVIDER=deepseek
export PROOFDEMO_DEEPSEEK_MODEL=YOUR_DEEPSEEK_MODEL
read -s "DEEPSEEK_API_KEY?请输入密钥（输入时不会显示）: "
echo
export DEEPSEEK_API_KEY
proofdemo-api
```

OpenAI 示例：

```bash
export PROOFDEMO_PLANNER_PROVIDER=openai
export PROOFDEMO_OPENAI_MODEL=YOUR_OPENAI_MODEL
export OPENAI_API_KEY="YOUR_LOCAL_KEY"
proofdemo-api
```

API 默认运行在 `http://127.0.0.1:8000`。可以检查：

```bash
curl http://127.0.0.1:8000/health
```

在第二个终端启动前端：

```bash
npm --prefix frontend run dev
```

打开 `http://127.0.0.1:5173`。API 和前端终端都需要保持运行。工作台会展示探索页面、规划结果、证据锚定、实时截图、操作事件、逐场景断言和最终视频。只有验证结果为 `PASSED` 且产物完整性复核通过时，视频才会交付。

### 关键行为边界

- 模型只能提出候选 DemoSpec，不能直接操作浏览器或宣布成功。
- 工作台最多只读探索 5 个同源页面；不会登录、注入凭据或提交探索表单。
- 点击/填写必须与实际观察到的唯一控件匹配，否则在执行前阻止。
- 同源普通链接在当前录制页面打开；跨源导航仍被阻止，下载链接保留下载语义。
- `EXECUTED` 只表示操作完成；全部确定性断言通过后才能得到 `PASSED`。
- 失败或阻塞的任务不会生成冒充成功的视频。
- 当前语言和时长是规划偏好，不保证精确时长或完整本地化。
- 视频润色使用真实交互坐标和已验证场景；没有证据时不会虚构缩放、结果或声明。

### 产物与重放

一次成功的确定性运行会生成执行报告、轨迹、浏览器日志、证据截图、`browser.webm`、1080p H.264 `demo.mp4`、产物清单和 `demo_recipe.json`。重放命令示例：

```bash
proofdemo replay artifacts/todo-demo/demo_recipe.json \
  --artifacts artifacts/todo-demo-replay
```

配方是可移植输入，不是执行授权。重放会重新检查兼容性、安全策略、断言和产物来源。

### 验证项目

```bash
proofdemo benchmark --output artifacts/benchmark_report.json
python -m pytest
ruff format --check .
ruff check .
mypy backend/src
npm --prefix frontend run build
```

权威 DemoSpec 模型位于 Python 领域层。修改模型后运行 `python scripts/export_schema.py`；schema 漂移会导致测试失败。

### 仓库结构与文档

```text
backend/src/proofdemo/  API、规划、执行、验证、媒体与适配器
frontend/               React/TypeScript 本地工作台
shared/schemas/         生成的跨运行时契约
examples/               本地 Todo/Notes fixture 与有效 DemoSpec
scripts/                确定性开发脚本
tests/                  领域、API、浏览器与媒体测试
docs/                   产品、架构、路线图和阶段范围
```

- [产品规格](docs/PROJECT_SPEC.md)
- [架构](docs/ARCHITECTURE.md)
- [路线图](docs/ROADMAP.md)
- [当前阶段](docs/CURRENT_STAGE.md)
- [威胁模型](docs/THREAT_MODEL.md)
- [运维指南](docs/OPERATIONS.md)
- [安全策略](SECURITY.md)

### 安全

绝不能提交密钥，也不能把凭据写入 DemoIntent、DemoSpec、日志或产物。`.env` 已被忽略，提供方适配器只从环境读取凭据。请只对你有权访问的非敏感站点运行 ProofDemo；页面截图和视频可能包含目标页面自身展示的信息。

---

## English

### Overview

ProofDemo is a verified product-demo system. A local user can enter a product URL and a goal, observe read-only exploration, planning, browser execution, and verification, and receive a playable video after the run succeeds.

The repository contains Engine V1, the local product studio, evidence-constrained same-origin exploration, and evidence-driven video polish. It is neither a general browser agent nor a hosted SaaS. See the [current stage](docs/CURRENT_STAGE.md) for the exact scope.

### Verified local success cases

The repository includes two fully local, reproducible cases that require no model API:

| Case | Shape | Verified behavior | DemoSpec |
| --- | --- | --- | --- |
| Todo | Single-page app | Fill and create a task, list text, URL, download, and application state | [`examples/demo_spec.json`](examples/demo_spec.json) |
| Notes | Two-page app | Same-origin navigation, fill and publish a note, result text, and URL | [`examples/notes_demo_spec.json`](examples/notes_demo_spec.json) |

Automated acceptance runs both sites through real Chromium, deterministic assertions, recording, FFmpeg composition, and video polish. These cases are evidence for the local product path, not a claim that every website will work.

#### Case 1: Todo

Terminal 1:

```bash
source .venv/bin/activate
python scripts/serve_todo_app.py
```

Terminal 2:

```bash
source .venv/bin/activate
proofdemo run examples/demo_spec.json --artifacts artifacts/todo-demo
```

#### Case 2: Notes

Terminal 1:

```bash
source .venv/bin/activate
python -m http.server 4174 --bind 127.0.0.1 --directory examples/notes_app
```

Terminal 2:

```bash
source .venv/bin/activate
proofdemo run examples/notes_demo_spec.json \
  --artifacts artifacts/notes-demo \
  --allow-risky-actions
```

The conservative safety policy classifies `Publish note` as a named publishing action, so the CLI requires explicit approval for that run. Approval is not inherited by replay or later runs.

### Requirements

- Python 3.11 or newer
- Node.js 20.19 or newer
- npm 10 or newer
- FFmpeg and FFprobe with H.264 support

### Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m playwright install chromium
cp .env.example .env

npm --prefix frontend install
cp frontend/.env.example frontend/.env.local
```

### Start the local studio

The deterministic CLI examples do not require a model key. Natural-language planning in the studio requires an explicitly configured provider.

DeepSeek example (keep the key only in the current terminal; never commit or paste it into chat):

```bash
export PROOFDEMO_PLANNER_PROVIDER=deepseek
export PROOFDEMO_DEEPSEEK_MODEL=YOUR_DEEPSEEK_MODEL
read -s "DEEPSEEK_API_KEY?Enter the key (input is hidden): "
echo
export DEEPSEEK_API_KEY
proofdemo-api
```

OpenAI example:

```bash
export PROOFDEMO_PLANNER_PROVIDER=openai
export PROOFDEMO_OPENAI_MODEL=YOUR_OPENAI_MODEL
export OPENAI_API_KEY="YOUR_LOCAL_KEY"
proofdemo-api
```

The API listens on `http://127.0.0.1:8000` by default. Check it with:

```bash
curl http://127.0.0.1:8000/health
```

Start the frontend in a second terminal:

```bash
npm --prefix frontend run dev
```

Open `http://127.0.0.1:5173`. Keep both API and frontend terminals running. The studio displays explored pages, the planned spec, grounding coverage, live screenshots, action events, per-scene assertions, and the final video. Video is delivered only when the result is `PASSED` and artifact integrity is revalidated.

### Key behavior boundaries

- A model may only propose a DemoSpec candidate; it cannot operate the browser or declare success.
- The studio explores at most five same-origin pages with read-only navigation; it does not log in, inject credentials, or submit exploration forms.
- Click and fill targets must match unique observed controls or execution is blocked beforehand.
- Ordinary same-origin links open in the recorded page; cross-origin navigation remains blocked and download links retain download semantics.
- `EXECUTED` means only that operations finished; every deterministic assertion must pass before the run becomes `PASSED`.
- Failed or blocked jobs never produce a video presented as successful.
- Language and duration are planning preferences, not exact guarantees.
- Video polish uses real interaction coordinates and verified scenes; it does not invent zooms, outcomes, or claims when evidence is absent.

### Artifacts and replay

A successful deterministic run produces an execution report, trace, browser log, evidence screenshots, `browser.webm`, a 1080p H.264 `demo.mp4`, an artifact manifest, and `demo_recipe.json`. Example replay:

```bash
proofdemo replay artifacts/todo-demo/demo_recipe.json \
  --artifacts artifacts/todo-demo-replay
```

A recipe is portable input, not execution authorization. Replay rechecks compatibility, safety policy, assertions, and artifact provenance.

### Validate the project

```bash
proofdemo benchmark --output artifacts/benchmark_report.json
python -m pytest
ruff format --check .
ruff check .
mypy backend/src
npm --prefix frontend run build
```

The Python domain model is the authoritative DemoSpec source. Run `python scripts/export_schema.py` after changing it; schema drift fails the test suite.

### Repository layout and documentation

```text
backend/src/proofdemo/  API, planning, execution, verification, media, adapters
frontend/               React/TypeScript local studio
shared/schemas/         generated cross-runtime contracts
examples/               local Todo/Notes fixtures and valid DemoSpecs
scripts/                deterministic development utilities
tests/                  domain, API, browser, and media tests
docs/                   product, architecture, roadmap, and stage scope
```

- [Product specification](docs/PROJECT_SPEC.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Current stage](docs/CURRENT_STAGE.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Operations guide](docs/OPERATIONS.md)
- [Security policy](SECURITY.md)

### Security

Never commit keys or place credentials in DemoIntent, DemoSpec, logs, or artifacts. `.env` is ignored and provider adapters read credentials only from the environment. Run ProofDemo only against non-sensitive sites you are authorized to access; screenshots and videos may contain information displayed by the target page itself.

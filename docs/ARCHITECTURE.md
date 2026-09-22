# ProofDemo 架构

## 当前形态

ProofDemo 从模块化单体起步，Web 和 API 进程可以分别运行：

```text
Frontend (React/TypeScript)
        |
        v
Backend API (FastAPI)
        |
        v
Application orchestration
   |       |       |
   v       v       v
Domain  Adapters  Persistence
```

在 V1 中，应用层包含一个有界规划服务，以及职责集中的确定性执行、验证、轨迹、产物持久化、合成、旁白、配方、重放预检和变化检测服务。它还包含有界修复验证、局部渲染策略、执行前安全门禁和离线基准。浏览器、媒体和提供方机制位于应用自有端口之后，分别由 Playwright Chromium、FFmpeg 和可选 OpenAI 适配器实现。

## 技术选型

- **Python 3.11+**：后端和核心产品逻辑。
- **FastAPI**：类型化、可检查的 HTTP 边界。
- **Pydantic v2**：权威运行时模型与 DemoSpec JSON Schema 来源。
- **Pydantic Settings**：经过验证的 `.env` 与进程环境加载。
- **React、TypeScript 和 Vite**：小型、可独立运行的前端。
- **pytest**：后端/领域测试；**Ruff** 和 **mypy**：静态检查。
- **Playwright**：在应用自有端口之后提供 Chromium 适配器。
- **FFmpeg/FFprobe**：在渲染端口之后提供通用媒体探测、缩放、加黑边和 H.264 编码。时间线策略由 ProofDemo 掌控。
- **OpenAI Responses API**：在规划器端口之后提供可选结构化规划；使用明确模型，不使用工具，也不保存对话。
- **OpenAI Speech API**：可选地在语音端口之后将已批准提示文本合成为 WAV。它不会接收断言载荷，也不会创作旁白。

## 仓库布局

```text
backend/src/proofdemo/  Python package, API, application, ports, and adapters
frontend/               React application
shared/schemas/         generated cross-runtime contracts
examples/               checked-in valid product inputs
scripts/                deterministic developer utilities
tests/                  domain and API tests
docs/                   product and planning sources of truth
```

Python DemoSpec 模型是权威来源。`scripts/export_schema.py` 将其 JSON Schema 导出到 `shared/schemas/demo_spec.schema.json`；测试会阻止已提交契约发生漂移。

## 依赖方向

预期依赖方向为：

```text
API / CLI -> application services -> domain <- adapters
```

领域代码不得依赖 FastAPI、Playwright、模型 SDK、持久化或渲染框架。适配器实现由应用层定义的边界。

## 确定性工作与模型负责的工作

| 关注点 | 负责方 |
| --- | --- |
| DemoSpec 验证 | 确定性领域代码 |
| 运行状态转换 | 确定性领域代码 |
| 浏览器操作 | 确定性 Playwright 适配器 |
| 断言 | 确定性验证器 |
| 轨迹/产物持久化 | 确定性轨迹记录器与产物写入器 |
| 视频合成 | 确定性渲染适配器 |
| 意图到 DemoSpec 的规划 | 窄边界之后的模型 |
| 有歧义的 UI 解析 | 模型辅助，并记录证据 |
| 旁白声明文本 | 根据已通过断言选择的确定性模板 |
| 语音合成 | 窄边界之后的提供方 |
| 音频对齐 | 确定性时间线策略与 FFmpeg 适配器 |
| 配方兼容性 | 确定性应用策略 |
| 重放执行 | 现有执行/验证/媒体服务 |
| UI 变化诊断 | 基于稳定 ID 的确定性证据比较 |
| 修复范围/应用 | 只允许目标替换的确定性策略 |
| 修复建议 | 无工具结构化输出端口之后的模型 |
| 局部场景来源选择 | 基于已验证产物的确定性策略 |
| 执行前安全决策 | 确定性应用策略 |
| 发布基准 | 基于应用服务的确定性 fixture |

## DemoSpec 执行契约

Schema 版本 `1.2` 为每个 Scene、Action 和 Assertion 使用稳定 ID，并要求每个场景至少包含一项断言。Scene ID 在一份规范内唯一；Action 和 Assertion ID 在其所属 Scene 内唯一。因此规范化关联键为：

```text
scene_id/action_id
scene_id/assertion_id
```

元素目标是由角色、标签、文本、测试 ID 和 CSS 选择器策略组成的可区分联合。每种策略的目标模型只公开该策略可以使用的字段。

`source_url` 定义首个确定性浏览器阶段允许访问的源站。第一个操作必须是显式 `goto`，并且每个 `goto` 都必须停留在该源站。跨源工作流需要未来单独设计明确的安全方案。

`pause` 是有界的演示延时。它不能替代 Playwright 就绪检查或定位器自动等待。

## 执行与验证边界

`ExecutionService` 接收已经验证的 DemoSpec、一个 `BrowserPort` 和产物目录。它按声明顺序执行每个场景的操作，将该场景的断言委托给 `VerificationService`，并生成 `ExecutionReport`。报告包含不可变 DemoRun、有序操作结果、场景/断言结果、请求的截图路径，以及聚合验证状态。

浏览器端口只包含 `open`、`goto`、`click`、`fill`、`pause`、`screenshot`、确定性观察和幂等 `close` 操作。Playwright 适配器负责定位器转换、浏览器生命周期、Playwright 错误转换、下载观察、受限应用状态读取，以及运行时同源强制。应用服务负责顺序、比较、证据模型、运行/场景转换、结果关联和受限截图路径。

浏览器启动和运行时可用性错误产生 `BLOCKED`。确定性失败的请求操作或可观察预期产生 `FAILED`。每个场景的每项断言都通过后，运行才会从 `EXECUTED` 转换为 `PASSED`。浏览器资源会在最终 `PASSED` 转换前以及每条失败路径上关闭。

DemoSpec `1.2` 支持 `element_visible`、`text_contains`、`url_equals`、`download_completed` 和 `app_state_equals`。证据在稳定的 `scene_id/assertion_id` 键下保存兼容 JSON 的预期值和观察值。应用状态断言只能从显式启用的 `window.__PROOFDEMO_STATE__` 对象读取一个经过验证的顶层键；规范不能提供可执行 JavaScript。

`examples/todo_app/` 下的 Todo fixture 有意独立于 ProofDemo 前端。它是确定性执行目标，不是产品 UI。

## 规划器边界

`PlanningService` 接收严格的 `DemoIntent` 和一个 `PlannerPort`。OpenAI 适配器进行一次结构化输出请求，其解析类型就是权威 DemoSpec 模型。它不具备浏览器、轨迹、执行或产物能力，也不能进入 DemoRun 生命周期。

ProofDemo 通过领域验证重新构建返回的模型，并拒绝规范化源站与请求源站不同的候选结果。该结果明确是需要审核的建议：`proofdemo plan` 原子写入候选文件，而 `proofdemo run` 始终是单独的用户操作。缺少模型或提供方配置只会阻塞规划；手工编写的 DemoSpec 无需访问模型，仍可进入确定性管线。

## 轨迹与产物边界

`TraceRecorder` 生成不可变、有版本的事件，包含连续序号、UTC 时间戳、稳定关联 ID、结果和兼容 JSON 的数据。操作轨迹载荷包含操作类型和结果，但绝不包含填充值。断言轨迹载荷可以包含 DemoSpec 已授权的非敏感预期证据和观察证据。

Playwright 适配器负责最终确定浏览器视频，并收集有界、经过清理的控制台与页面错误。它只在关闭浏览器上下文后返回这些内容。可选采集失败时，`ExecutionService` 会协调自动证据截图，但不会更改验证器结果。

`ArtifactWriter` 原子写入报告、轨迹和浏览器日志，然后将这些文件与请求的截图、证据截图和浏览器视频一起计算哈希。`artifact_manifest.json` 为其他每项产物记录 SHA-256、字节数、媒体类型和关联元数据；清单无法在密码学意义上包含自身。使用前，所有产物路径都会被解析，并检查其是否位于请求的根目录之内。

## 时间线与渲染边界

`CompositionService` 只接收经过完整性检查，且运行状态与验证状态均为 `PASSED` 的 Stage 3 bundle。它通过按探测到的浏览器视频时长缩放关联操作/场景轨迹时间，把稳定场景 ID 映射到连续毫秒区间。有版本的时间线始终完整覆盖源视频，各场景区间为正数、有序且互不重叠。

FFmpeg 适配器只接收源路径、输出路径和固定渲染设置。Stage 4 合成使用 1920×1080 画布、30 fps、保持宽高比的 Lanczos 缩放、固定黑边颜色、H.264/yuv420p、无音频、移除元数据，并使用单一编码线程以提高可重复性。渲染后，FFprobe 会验证尺寸、帧率、编解码器和时长。随后，`timeline.json` 和 `demo.mp4` 会被写入最终产物清单并计算哈希。

## 旁白与音频边界

`NarrationService` 只接收已验证的 `PASSED` bundle、通过完整性检查的 Stage 4 清单，以及其精确持久化时间线。它按确定性优先级为每个场景选择一项已通过断言，并将断言类型映射到由项目定义的短句。`validate_narration_grounding` 会重新计算允许的短句、断言引用、场景身份和时间线边界；不接受模型自由创作的成功文本。

`SpeechPort` 只接收已批准的提示文本。OpenAI 适配器要求明确的模型和语音，请求 PCM WAV，原子发布文件，并且不获得控制证据或时序的权限。第一条提示包含口述的 AI 语音声明。

每个 WAV 使用前都会被探测。语音最多可加速 2 倍，以放入它自己的已验证场景；更长语音会被拒绝，而不是截断或移动。`AudioMixPort` 对齐提示、填充静音，并在加入 AAC 音频时保留 Stage 4 H.264 视频流。旁白轨道、关联 WAV 文件和带旁白 MP4 都会纳入完整性清单。

## DemoRun 生命周期

V1 保持以下合法状态图；规划、渲染、旁白、重放预检、变化检测和修复合成都不能改变它：

```text
CREATED -> VALIDATED -> RUNNING -> EXECUTED -> PASSED
    |          |          |          |
    |          |          |          `-> FAILED / BLOCKED
    |          |          |------------> FAILED / BLOCKED
    |          |-----------------------> FAILED / BLOCKED
    `----------------------------------> FAILED / BLOCKED
```

`EXECUTED` 表示所有请求的浏览器操作已经完成；它并不是经过验证的成功结果。只有基于证据的验证才能允许 `EXECUTED -> PASSED`。

`PASSED`、`FAILED` 和 `BLOCKED` 都是终态。状态转换函数是纯函数：它构造经过完整重新验证的模型，并追加一条不可变历史记录。所有时间戳都包含时区并规范化为 UTC。

## 配方与重放边界

`DemoRecipe` 嵌入规范化 DemoSpec 及其语义 SHA-256 指纹、固定的 Chromium/headless/1280×720 执行 profile、受支持 schema 要求、生成器版本和源运行来源。来源信息通过清单哈希引用经过验证的执行报告和首选最终视频。它不包含浏览器存储、凭据、环境值、提供方密钥或日志。

`RecipeService` 只根据已验证的 `PASSED` bundle 和通过完整性检查且运行/规范身份匹配的清单创建配方。Playwright 创建前，兼容性检查会把每项不受支持的配方/schema/引擎/profile 约束和指纹不匹配收集到 `replay_preflight.json`。

兼容的重放会把嵌入的 DemoSpec 传给相同的 CLI 编排、`ExecutionService`、验证器、产物写入器和媒体服务。预检报告会记录到新运行的清单中；重放获得新的运行 ID，并生成新配方。语音仍然是独立的明确按需选项。

## 变化检测边界

比较前，`ChangeDetectionService` 会在选定基线目录内解析源执行报告，根据配方来源信息验证其 SHA-256，解析严格的报告 schema，并要求源运行、规范和 `PASSED` 状态均匹配。明确指定但缺失或无效的基线会在浏览器构建前停止流程。

重放后，服务根据稳定的 `scene_id/action_id` 和 `scene_id/assertion_id` 比较基线与当前结果。它会分类缺失或失败的操作、可能的定位器/选择器失败、失败断言、已通过但观察值变化的断言，以及失效的场景假设。流程不使用视觉启发式或模型。即使重放失败，`ui_change_report.json` 仍会被持久化，并且绝不会改变验证或生命周期状态。缺少本地基线的复制版可移植配方仍可重放，但报告会明确标记为 `NOT_EVALUATED`。

## 修复与局部渲染边界

`RepairService` 只加载属于所提供配方、并已记录完整性的 `CHANGED` 报告。`RepairPort` 可以为一个已诊断场景提出类型化目标替换。确定性验证要求每项替换都指向现有且已诊断的 click/fill 操作或 element/text 断言；拒绝未发生变化的目标，并阻止对其他任何 DemoSpec 字段或顺序的修改。`propose-repair` 只写入待审核候选；`apply-repair` 是明确的批准边界。

获得批准的建议会重新构建权威 DemoSpec，然后使用正常执行器和验证器。只有新运行完全达到 `PASSED`，且基线清单和修复后清单都通过完整性检查，`PartialRenderService` 才会运行。它要求场景集合完全相同，并且修复场景之外的契约没有变化。由项目掌控的计划为该场景选择修复后 `demo.mp4` 的时间范围，其他场景则选择基线时间范围。FFmpeg 适配器对这些范围进行裁剪和拼接，生成无声的 `demo-repaired.mp4`；计划记录全部源哈希及输入/输出边界。局部旁白/音频重新生成被有意推迟。

## 安全与基准边界

`SafetyService` 会在 Playwright 构建前检查已经验证的 DemoSpec。类似凭据的填充目标无论是否批准都会被阻止；具名的破坏性、金融、账户和生产环境点击需要新的 CLI 确认。结果会被原子写入 `safety_assessment.json`；执行继续时，该文件会纳入产物清单。批准只是一次命令的输入，不属于配方来源信息，因此重放和修复都必须再次请求批准。

`BenchmarkService` 使用确定性的内存浏览器适配器，让固定的成功、断言失败、操作失败和浏览器阻塞案例经过 `ExecutionService`。它衡量终态结果准确率、预期证据覆盖率和轨迹序列/关联完整性。它绝不会构建真实浏览器、媒体适配器、提供方客户端或网络请求。这些 fixture 是 V1 语义的回归/发布门禁，不是可用性或通用 Web 自动化基准。

## 配置与安全

配置来自 `.env` 和 `PROOFDEMO_` 环境变量，真实环境变量优先。配置中没有密钥默认值。文档中的前端和 API 默认值都使用 `127.0.0.1`。API 只公开非敏感服务元数据。浏览器导航被限制在已验证源站，截图不能逃逸其产物目录，字面填充值按契约只能是非敏感演示数据。应用状态 hook 把经过验证的键当作数据，而不是代码。诊断日志有界且会被清理，填充值不会复制到操作轨迹载荷中。提供方凭据只从环境配置读取，绝不会进入 DemoIntent、DemoSpec、轨迹或产物。语音只接收固定、非敏感短句。配方省略环境快照、浏览器会话状态和凭据。V1 不支持浏览器凭据注入。DemoSpec 集合大小和暂停总时长均有边界。生产设置要求 HTTPS 前端源站、禁用交互式 API 文档，并启用 HSTS、CSP 和防御性 API 响应头。

## 有意推迟的工作

V1 有意不包含模型工具、模型编写旁白、自主探索、通用定位器修复、编辑转场、缩放、覆盖层、字幕、音乐、数据库、队列、后台工作进程、自主/多场景修复、局部旁白、认证、托管式控制平面或云产物存储。任何后续新增能力都必须先定义范围明确的规格并证明有实测需求，不能从 V1 已完成这一事实中自行推导。

## Stage 11 — 本地产品工作台（已完成）

Stage 11 在原有 FastAPI 和 React 进程中增加产品入口，不修改 DemoRun 的验证状态机。`POST /jobs` 接受 `DemoIntent`，本地 `JobManager` 用一个后台线程运行原有 `PlanningService`、`SafetyService`、`ExecutionService`、`ArtifactWriter`、`CompositionService` 与 `RecipeService`。这是本地单进程执行槽，不是可跨进程协调的持久队列；同时最多有一个非终态任务。CLI 的 `plan`/`run` 语义仍然独立。

任务状态与安全发现原子写入 `job.json`，进度事件追加到 `events.jsonl`，候选规范和运行产物位于该任务的受限目录。任务重启恢复时，未到终态的任务转为 `BLOCKED`，绝不自动重试可能已有外部效果的浏览器操作。审批只对规划时记录的规范指纹有效；执行前重新计算规范指纹并重新评估安全策略。计划中出现类似凭据的填充始终阻止执行，具名风险操作需要单独调用审批接口。

`ExecutionService` 的可选观察器把已脱敏的轨迹元数据推送为 SSE；不发送填充值或断言观察载荷。每项操作后可选择更新 `preview/latest.png`，截图失败不改变验证结果。UI 可获取候选规范、执行报告、完整性清单和预览；只有任务为 `PASSED` 且最终清单重新通过哈希验证时才提供视频。当前 UI 无账号或授权机制，因此服务默认只监听回环地址，不能作为公网服务部署。截图和视频本身可能包含被演示站点展示的敏感数据；用户必须只演示已获授权、非敏感的工作流，并管理本地产物保留。

Stage 11 当时的工作台没有站点探索能力，单次规划仍依赖用户目标和模型已有线索。后续 Stage 12 在明确预算与安全边界内增加有证据约束的探索，Stage 13 增加视频润色；这些增量仍不能证明对任意陌生网站可靠。Stage 14 才评估托管服务。

## Stage 12 — 有证据约束的只读探索（已完成）

仅工作台任务在规划前运行 `ExplorationService`；CLI 的 `plan` 不改变。隔离的 `PlaywrightExplorer` 使用全新无凭据上下文，阻止非 GET、跨源请求、下载链接与所有重定向，不点击或填充页面。应用层额外筛掉风险路径、下载扩展名和可能包含秘密的查询键；最多访问 5 页，保留每页最多 120 个可见控件、50 个候选链接，采用总时间预算和逐页导航超时。`OpenAILinkAdvisor` 的结构化建议只能选择精确位于已观察安全候选集合中的 URL；页面内容始终视为不可信数据。

每页实际 URL、标题、有限标题层级、可操作控件的唯一定位、导航来源与截图哈希写入版本化 `exploration_report.json`。报告中的 `COMPLETE` 只表示当前安全候选已访问完，不表示理解整个产品。工作台可查看页面、截图、警告和进度；页面截图本身可能含敏感内容，必须只使用获授权的非敏感站点。GET 也可能被目标服务器设计成有副作用，因此“只读”仅表示 ProofDemo 不有意提交表单或发出写方法，不能构成对站点状态绝对不变的保证。

模型基于报告生成 DemoSpec 候选后，`GroundingService` 将每个 goto 限定为实际访问页，将每个点击/填充目标限定为当页已观察且唯一定位的控件。点击已观察链接时，只有目的页也实际被访问才可继续在目的页操作。暂停与截图是展示动作，不需要控件锚定；断言仍是待执行的假设，由原有验证器给出结果。无法锚定的动作直接 `BLOCKED`，并在 `grounding_report.json` 留下具名缺口。探索报告、锚定报告、截图和候选规范有哈希绑定，审批后执行前重新核对锚定与安全策略。两套本地 fixture 的真实浏览器/媒体贯通测试证明这条管线可运行，但并非真实模型对任意网站的成功率证据。

## Stage 13 — 证据驱动的视频润色（已完成）

`ExecutionService` 对 click/fill 可选读取元素在当前视口的归一化中心坐标，仅把有界数值写入 `ACTION_STARTED` 轨迹；失败被忽略，不影响操作、断言或 `PASSED`。`VideoPolishService` 仅接受运行与所有断言通过、源清单哈希有效、时间线匹配且 H.264 基础视频媒体属性符合预期的输入。它从源场景区间、已成功操作的真实坐标和轨迹时间构造版本化 `VideoPolishPlan`。最多处理 12 个场景、24 个焦点提示；缺少几何证据时保持静态镜头并记录警告，不猜测目标位置。

离线 Chromium 使用固定 HTML/CSS，把场景标题和断言通过计数作为 `textContent` 绘制为透明 PNG；不加载目标站点，也不将文本插入 FFmpeg 滤镜语法。FFmpeg 只接收数值型滤镜表达式，按原始顺序拼接场景，并在每个场景后加入 800 毫秒已验证结果保持帧；焦点提示采用短时缩放和平滑光标，字幕与验证标注渐入/渐出，相邻场景有 80 毫秒黑场式过渡。字幕是场景标题及断言计数，不是语音转写；TTS 不会自动混入工作台视频。润色层不会重新定义或修改验证事实。

工作台任务增加 `POLISHING` 状态，成功后将基础 `demo.mp4`、`polish_plan.json`、`polish_captions.json`、透明覆盖层和独立 `polished_demo.mp4` 一并纳入最终哈希清单。`GET /jobs/{id}/polish-plan` 与视频接口读取时复核清单；只在任务 `PASSED` 且视频类型为润色版时提供编辑计划。CLI/旧任务继续使用基础视频。Chromium 或 FFmpeg 润色失败显式 `BLOCKED`，不回退伪装为成功的润色版。当前使用 FFmpeg 而非 Remotion：独立编辑模板、动态逐词字幕或复杂动效需求尚未获得实际使用证据。

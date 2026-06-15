# autotest_iot — ESP32-S3 嵌入式自动化复测/修复闭环

把"取 Jira 缺陷 → 智能体操控硬件复测 → 抓 log 诊断 → 改代码 → 编译烧录 → 复测 → 知识沉淀"做成**软硬一体的智能体闭环**，全部可注入、可单测（**77 测试全绿**）。

```
Jira缺陷 ─▶ ReproPlanner ─▶ 硬件复现 ─▶ 符号化 ─▶ Diagnostician
   ─▶ Fixer ─▶ PR(人工门: 飞书审批 / PR合并) ─▶ rebuild ─▶ flash ─▶ 复测 ─▶ verdict
                                          └─ pass → Summarizer → 知识库 ──(下次召回)
控制面(VPS唯一入口) + 硬件网关注册/心跳/离线队列 + LangGraph 状态机(重试/回退/终态)
真 Jira + 真 GitHub + 飞书审批
```

## 🚀 部署到真实环境

**完整逐步配置 + 验证 + 排错见 [`docs/DEPLOY.md`](docs/DEPLOY.md)。** 设计见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

快速起步：

```bash
git clone https://github.com/liuyuyan6100/autotest-iot.git && cd autotest-iot
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[test]" && pytest -q            # 无硬件/无 key 也应全绿
cp config/boards.yaml.example config/boards.yaml  # 按 DEPLOY.md §3 填
# 无 key/无板先跑通逻辑：
python -m autotest_mcp.run_orchestrate BUG-123 --fake --source /tmp/fw --gate auto
```

必填配置速查（详见 DEPLOY.md §3）：板子 COM 口 · `tools.idf_version`/`addr2line` · 控制面 token · `jira.backend:rest`+凭据 · `feishu.approval_code`+app 凭据 · `ANTHROPIC_API_KEY`。

---

## 已实现的能力

### M0：硬件 MCP 网关

7 个 MCP tool，让本地/远程智能体作为 client 调用：

| tool | 作用 | 占板级锁 |
|---|---|---|
| `list_boards` | 列出已注册板子 + 在线探测 | 否 |
| `build` | 编译固件（docker `espressif/idf` 或本地 `idf.py`） | 否 |
| `flash` | esptool 烧录（`.bin` 或 build 目录的 `flash_args`） | 是 |
| `capture_serial` | 抓 UART → 落盘日志，监听 panic，可注入串口命令 | 是 |
| `symbolize` | panic backtrace 地址 → 函数+文件:行 | 否 |
| `press_button` | 继电器按压物理按键 | 是 |
| `power_cycle` | 继电器断电再上电 | 是 |

触板动作走板级锁（`queue` 排队 / `reject` 立即返回 busy），两个 agent 同时操作同一块板不会打架。

## 安装（Windows 目标机 / 当前 Ubuntu 开发机皆可）

```bash
python3 -m venv .venv
. .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[test]"
```

## 配置

```bash
cp config/boards.yaml.example config/boards.yaml
# 编辑：板子 COM 口 / 继电器通道 / bind host / token
```

- **家用原型**：`server.host` 填 tailscale 网卡 IP，VPS 经 tailnet 访问。
- **公司**：`server.host` 填内网/VPN IP，开 `mtls`，对接公司 CA。
- token 也可用环境变量覆盖：`AUTOTEST_TOKEN=...`（不入库）。

## 运行

```bash
# HTTP（默认，本地 + 远程都可接）
python -m autotest_mcp.server
# 等价于设置 transport: http；监听 http://<host>:<port>/mcp

# stdio（本地排错）
AUTOTEST_... # 在 config 设 transport: stdio，或临时改 yaml
python -m autotest_mcp.server
```

## 接入 Claude Code

在 Claude Code 的 MCP 配置里加（本地）：

```json
{
  "mcpServers": {
    "autotest": {
      "url": "http://localhost:8787/mcp",
      "headers": { "Authorization": "Bearer <你的 token>" }
    }
  }
}
```

远程（VPS / 同事机）把 `localhost` 换成 Windows 的可达 IP（家用 = tailscale IP，公司 = 内网 IP）。

## 测试

```bash
pytest -q          # 30 个单测，全 mock，无需硬件
```

## 端到端冒烟（Windows + 真板）

1. `config/boards.yaml` 填好板子 COM 口、token。
2. `python -m autotest_mcp.server` 起服务。
3. Claude Code 接入后依次调用：`build`（或用现成固件）→ `flash` → `capture_serial`（触发一次 panic）→ `symbolize`，确认 backtrace 还原成函数名。
4. 本地与远程 client 同时 `flash` 同一块板，验证锁生效（一方排队或返回 busy）。
5. `press_button` / `power_cycle` 在 MockRelayBackend 下会打印/记录动作时序（无真继电器时）。

## 目录

```
src/autotest_mcp/
  server.py            # M0 硬件网关（FastMCP 注册所有 tool + 启动）
  transport.py         # bearer 鉴权 + mTLS + uvicorn（tailscale 不进代码）
  concurrency.py       # 板级锁（queue/reject）
  config.py            # YAML + env 加载
  tools/               # device / symbolizer / serial_mon / flasher / builder / hardware
  defects/             # Defect 模型 + MockJiraClient + JiraRestClient + make_jira 工厂
  agents/              # ReproPlanner / Diagnostician / Fixer / Summarizer
  pipeline.py          # M1 复现+诊断
  fix_pipeline.py      # M2 修复+复测闭环
  git_client.py        # apply_file_edits + GhGitClient + FakeGitClient + GithubPrChecker
  knowledge/           # Case + File/Vector KnowledgeStore + recall
  feishu/              # 飞书审批门（gate + driver）
  control_plane/       # Registry + JobQueue + ControlPlane + registrar + server
  orchestrator/        # LangGraph 状态机（重试/人工门/终态/检查点）
  run_m1.py / run_m2.py / run_m3.py / run_orchestrate.py / run_control_plane.py / run_gateway_register.py
config/boards.yaml.example, config/defects.example.yaml
docs/ARCHITECTURE.md, docs/DEPLOY.md
tests/                 # 77 个 mock 单测（无硬件/无 key 全绿）
```

---

## M1：复现 + 诊断 pipeline

在 M0 硬件能力之上，加了两个智能体 + 一条编排 pipeline：

```
Defect(mock Jira) ─▶ ReproPlanner(Claude) ─▶ 执行硬件复现(MCP client)
                                                       │
                                            symbolize(地址→函数名)
                                                       │
                                  Diagnostician(Claude) ─▶ Diagnosis 报告
```

组件：
- `llm.py` — Anthropic client 封装（opus-4-8 + adaptive thinking + effort），结构化输出，client 可注入。
- `defects/` — 结构化 `Defect`/`ReproStep` + `JiraClient` 接口 + `MockJiraClient`（读 yaml，初期不接公司真实系统）。
- `agents/repro_planner.py` — ReproPlanner；**串口命令白名单是硬安全门**（非白名单命令被拒绝并留痕）。
- `agents/diagnostician.py` — Diagnostician，读已符号化的 log 给根因诊断。
- `mcp_client.py` — `HardwareClient` 协议 + `McpHardwareClient`(streamable-http 调 M0 网关) + `FakeHardwareClient`(无板测试)。
- `pipeline.py` — 编排：规划→flash/按键/capture→符号化→诊断→`RunReport`。
- `run_m1.py` — CLI 入口。

### 跑

```bash
# 本地无 key/无板（fake LLM + fake 硬件，验证 pipeline 逻辑）
python -m autotest_mcp.run_m1 BUG-123 --fake --defects config/defects.example.yaml

# 真实（Windows + ANTHROPIC_API_KEY + 硬件网关在跑）
AUTOTEST_TOKEN=... python -m autotest_mcp.run_m1 BUG-123
```

测试：`pytest -q`（含白名单过滤、pipeline 端到端、诊断产出）。

> M1 的 LLM/硬件/符号化都可注入，所以**当前这台 Ubuntu 无 key 无板也能开发+单测**；真实运行在 Windows + key 上。命令白名单在 `config/boards.yaml` 的 `agents.test_command_whitelist`，固件组固化测试模式命令后导出清单填进来。

---

## M2：修复 + 复测闭环

闭合"诊断→修复→验证"的环（整条流水线最有价值的一段）：

```
Diagnosis ─▶ Fixer(Claude, 产 FileEdit) ─▶ GitClient 开 PR ── ══ 人工门 ══
                                                              │（人 review 合并）
                                              rebuild → flash → 复测 → verdict(pass/fail)
```

组件：
- `agents/fixer.py` — Fixer：诊断+源码 → 最小 `FileEdit`(str_replace 式) + rationale + risk_level。
- `git_client.py` — `apply_file_edits`(纯函数，可单测) + `GitClient` 协议 + `GhGitClient`(走 `gh` 开 PR) + `FakeGitClient`。
- `fix_pipeline.py` — `propose_fix`(产 PR，停在 `awaiting_review` 人工门) + `run_retest`(build→flash→复测→pass/fail/inconclusive)。
- `run_m2.py` — CLI：M1 诊断 → M2 产 PR →（合并后）复测。

### 人工门（核心安全约束）

**所有 patch 一律走 PR review**，不因 risk_level 自动合并。`propose_fix` 开完 PR 就停在 `awaiting_review`；只有人 review 合并后，`run_retest` 才针对已合并源码 rebuild+flash+复测。

### 跑

```bash
# 本地全 fake（假 LLM + 假 git + 假硬件，自动走完复测，模拟修复生效）
python -m autotest_mcp.run_m2 BUG-123 --fake --source /tmp/fw

# 真实（Windows + key + gh + 板子）：先拿 PR，人合并后加 --retest
AUTOTEST_TOKEN=... python -m autotest_mcp.run_m2 BUG-123 --source <固件仓库>
# 合并后：
ANTHROPIC_API_KEY=... python -m autotest_mcp.run_m2 BUG-123 --source <固件仓库> --retest
```

测试：`pytest -q`（含 apply_file_edits 增改/唯一性校验、Fixer 落地、复测 pass/fail/inconclusive 判定）。

---

## M3：知识库（RAG，越用越聪明）

每次闭环通过后，Summarizer 把全过程浓缩成结构化 `Case` 入库；下次诊断/修复前召回相似案例注入上下文。

```
复测 pass ─▶ Summarizer(Claude) ─▶ Case ─▶ KnowledgeStore
                                              ▲ 召回
下次诊断/Fixer ─▶ recall_context(相似案例) ──┘
```

组件：
- `knowledge/store.py` — `KnowledgeStore` 协议 + `FileKnowledgeStore`(JSON+关键词打分，离线默认) + `VectorKnowledgeStore`(chromadb，`pip install -e ".[vector]"`)。
- `knowledge/models.py` — `Case` 结构化案例。
- `knowledge/recall.py` — `recall_context` 把召回案例格式化进 agent 上下文。
- `agents/summarizer.py` — 闭环 → `Case`。
- 接线：`run_repro_diagnose(knowledge=)` 诊断前召回；`run_retest(...knowledge=)` 复测 pass 后沉淀。

### 跑（带知识库）

```bash
# 全 fake：复现→诊断→PR→复测 pass→沉淀，一个命令走完
python -m autotest_mcp.run_m2 BUG-123 --fake --source /tmp/fw --kb /tmp/kb.json

# 检索知识库
python -m autotest_mcp.run_m3 --kb /tmp/kb.json search "按键 panic"
python -m autotest_mcp.run_m3 --kb /tmp/kb.json show
```

> 默认 `FileKnowledgeStore`（无依赖、CJK 2-gram + 关键词加权打分，可单测）。生产换 `VectorKnowledgeStore`（chromadb 真 embedding 召回），协议一致、代码不变。失败案例不沉淀（避免污染知识库）。

---

## LangGraph 状态机编排

把线性 pipeline 升级为显式状态图，补上控制流：

```
START → intake → run_m1 → propose_fix → human_gate → retest → decide
                            ▲                              │
                            │回退重试(attempt<max)          ├ pass → deposit → END
                            └──────────────────────────────┤
                                                           └ 超限/inconclusive → escalate → END
```

- **重试/回退**：复测失败且未超 `max_attempts` → 回 `propose_fix` 重新修复，而非单发。
- **人工门**：`human_gate` 用 LangGraph `interrupt` 真正暂停等 PR review 合并；`Command(resume=True)` 续跑。
- **终态**：`closed`（复测通过+沉淀）/ `escalated`（超限转人工）。
- **检查点**：`MemorySaver`，任意阶段暂停可续跑（生产换持久 checkpointer 时需注册 state 里的 pydantic 类型）。

组件：`orchestrator/graph.py`（`build_orchestrator(deps)` 工厂 + `Deps` 依赖注入）；`run_orchestrate.py` CLI。

### 跑

```bash
# 全 fake 全自动（演示复现→修复→人工门auto→复测通过→沉淀）
python -m autotest_mcp.run_orchestrate BUG-123 --fake --source /tmp/fw --kb /tmp/kb.json

# 真实：跑到人工门暂停，人合并 PR 后 stdin 确认续跑
ANTHROPIC_API_KEY=... python -m autotest_mcp.run_orchestrate BUG-123 --source <仓库> --kb /tmp/kb.json
```

测试：`pytest -q`（含一次通过 / 重试后通过 / 超限转人工 / interrupt 暂停+resume 四个状态机场景）。

---

## 控制面（VPS 常驻唯一入口）+ 注册中心 + 离线队列

§1.5 两层架构落地：VPS 上常驻控制面，硬件网关（贴板子的 Windows/实验室机）按需上线注册；所有 agent/同事只对接控制面，硬件请求由控制面路由到在线网关，离线则入队、上线后续跑。

```
agent/同事 ──▶ 控制面(VPS, 24h) ──┬─ logic-bound tool：本地直接做
                                  └─ hardware-bound：路由到在线网关 / 离线入队
硬件网关(按需上线) ──注册+心跳──▶ 控制面 Registry（TTL 判上下线）
```

组件：
- `control_plane/registry.py` — 注册 / 心跳 / TTL 上下线 / 按板定位在线网关（clock 可注入）。
- `control_plane/queue.py` — 离线请求 JobQueue（按板分组、状态流转）。
- `control_plane/plane.py` — `ControlPlane`：路由在线网关 / 离线入队 / 网关上线 `drain_pending` 续跑。
- `control_plane/registrar.py` — `GatewayRegistrar`：网关侧注册+心跳（http poster 可注入）。
- `control_plane/server.py` — FastMCP 控制面（`call_hardware`/`list_gateways`/`register_gateway`/`heartbeat` tool）+ `/gateways` HTTP 路由 + bearer 鉴权。
- CLI：`run_control_plane.py`（起控制面）、`run_gateway_register.py`（网关注册+心跳）。

### 跑

```bash
# 1) VPS 上起控制面（唯一入口）
AUTOTEST_CP_TOKEN=... python -m autotest_mcp.run_control_plane

# 2) 贴板子的机器上：起硬件网关(M0) + 向控制面注册
python -m autotest_mcp.server                        # M0 硬件网关
python -m autotest_mcp.run_gateway_register          # 注册+心跳到控制面

# 3) 任意 agent/同事：把 mcp.url 指向控制面，调 call_hardware 即可（透明路由/排队）
```

> Windows 不 24h：它按需上线注册、关机 TTL 超时标离线；请求在线则路由、离线则排队续跑。核心逻辑纯 async、无网络可单测（clock/client/http 全可注入）。

---

## 飞书审批门（lark-approval）

把编排器的人工门从「PR review / stdin 回车」升级为**飞书审批实例**：graph 在 `human_gate` 处 interrupt → driver 创建飞书审批并轮询 → 通过则 `Command(resume=True)` 续跑、拒绝/超时则 `resume=False` → 走 **rejected 终态**（不再无脑继续）。

```
... → propose_fix → human_gate(interrupt) ──╮
                              飞书审批通过 ─→ resume=True  → retest → ...
                              审批拒绝/超时 ─→ resume=False → rejected → END
```

组件：
- `feishu/gate.py` — `ApprovalGate` 协议(create/status) + `LarkApprovalGate`(Feishu OpenAPI v3：建实例/查状态，tenant token 用 app_id/secret 换，http 可注入，`_parse_status` 纯函数兼容字符串/整数状态码) + `FakeApprovalGate`。
- `feishu/driver.py` — `await_approval_and_resume`：建审批 → 轮询 → resume（clock/sleep 可注入）。
- 接线：orchestrator 加 `approved` 状态 + 条件边（通过→retest / 拒绝→rejected→END）；`run_orchestrate --gate {auto,stdin,feishu}`。

> lark-cli 的 approval 模块没有"创建实例"命令，所以走 OpenAPI（`POST /approval/v3/instances` + `GET .../instances/{code}`）。真实运行需在飞书后台定义审批流程（`approval_code`）+ app 凭据；逻辑在此用 `FakeApprovalGate` 全测。

### 跑

```bash
# 飞书审批门（真实）：跑到 gate 暂停 → 建飞书审批 → 轮询 → 通过则续跑复测
ANTHROPIC_API_KEY=... LARK_APP_ID=... LARK_APP_SECRET=... \
  python -m autotest_mcp.run_orchestrate BUG-123 --source <仓库> --gate feishu
```

测试：`pytest -q`（含 `_parse_status`、driver 通过→closed / 拒绝→rejected / 超时、LarkApprovalGate http 注入与 token 缓存）。

---

## 真 Jira / GitHub 接口（替换 mock）

缺陷源与代码门都接真系统，由配置切换：

- **JiraRestClient**（`defects/jira_rest.py`）：Jira Cloud REST api/2，`GET /issue/{key}` 取缺陷、`POST /issue/{key}/comment` 回写；basic auth（email:api_token）；http 层可注入；`_map_issue`/`_parse_repro` 把 Jira 字段映射成 `Defect`（结构化复现步骤来自可配置的自定义字段 `jira.repro_field`）。
- **GithubPrChecker**（`git_client.py`）：`gh pr view <url> --json state,mergedAt` 查 PR 是否合并，runner 可注入——让人工门能真等"PR 合并"。
- **`make_jira(cfg)`** 工厂：按 `jira.backend`（mock|rest）选实现；三个 CLI（run_m1/m2/orchestrate）统一走它。

### 配置（config/boards.yaml）

```yaml
jira:
  backend: rest                 # mock | rest
  base_url: "https://yourorg.atlassian.net"
  email: ""                     # 或 env JIRA_EMAIL
  token: ""                     # API token；或 env JIRA_TOKEN
  repro_field: "customfield_10001"  # 存结构化复现步骤的字段（可选）
```

> Jira 凭据/字段结构各家不同，所以 http/subprocess 全可注入、`_map_issue` 是纯函数——这台 Ubuntu 无 Jira 实例，照样 77 测试全绿（含 `_map_issue`、JiraRestClient http 注入、GithubPrChecker merged/open/fail、make_jira 工厂）。真实运行在用户机器配 `backend: rest` + 凭据即可。

# autotest_iot — ESP32-S3 嵌入式自动化硬件 MCP 网关（M0）

把"硬件闭环"最底层的确定性能力（编译 / 烧录 / 抓串口 log / 符号化 backtrace / 继电器控电）做成一个 **MCP server**，让本地或远程的智能体作为 client 调用。

> 设计与边界见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。M0 只覆盖硬件能力；Jira/Git/知识库/编排/agent 是 M1+。

## M0 能做什么

注册 7 个 MCP tool：

| tool | 作用 | 是否占用板级锁 |
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
  server.py        # FastMCP 注册所有 tool + 启动
  transport.py     # bearer 鉴权 + mTLS + uvicorn（tailscale 不进代码）
  concurrency.py   # 板级锁（queue/reject）
  config.py        # YAML + env 加载
  tools/           # device / symbolizer / serial_mon / flasher / builder / hardware
config/boards.yaml.example
tests/             # 每个 tool 的 mock 单测
```

## 尚未实现（M1+）

Jira/Git/知识库 tool、VPS 控制面 + 注册中心 + 离线队列、LangGraph 编排与 4 个 agent、测试模式串口命令协议。

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

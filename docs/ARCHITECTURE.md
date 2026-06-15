# autotest_iot 架构设计

> ESP32-S3 嵌入式自动化复测 / 修复闭环系统。
> 把"取缺陷单 → 复现 → 抓 log → 诊断 → 改代码 → 编译烧录 → 复测 → 沉淀"做成软硬一体的智能体自治流水线。

---

## 0. 设计总原则（不可妥协）

1. **模型只"理解 + 决策 + 生成"，绝不直接执行。** 每个动作都由确定性、可单测的工具层执行，模型产出结构化指令，工具回传结果。这条原则是整个架构的安全基石。
2. **流程是显式状态机，不是 ReAct 自由发挥。** 每个阶段有明确的 成功 / 失败 / 需人工 三条出口，才可控、可重放、可审计。
3. **高风险动作必须人工门。** 代码修改在合并与烧录前必须经过人确认（MR/PR review 或飞书审批）。
4. **每一步都留痕。** 单次缺陷闭环全过程的 log、prompt、工具调用、diff 都落盘，既是审计材料，也是知识库原料。

---

## 1. 系统全景

```
┌─────────────────────────────────────────────────────────────┐
│            编排层  Orchestrator (LangGraph 状态机)            │
│   定义阶段 / 重试 / 人工门 / 失败回退 / 全程留痕              │
├─────────────────────────────────────────────────────────────┤
│            智能体层  Agents (只理解+决策+生成)                 │
│   ReproPlanner · Diagnostician · Fixer · Summarizer          │
├─────────────────────────────────────────────────────────────┤
│            工具层  Tools (确定性，每个可独立单测)              │
│  JiraClient · GitClient · Builder · Flasher                  │
│  SerialMonitor ─▶ Symbolizer · HardwareController            │
│  KnowledgeStore(RAG)                                         │
├─────────────────────────────────────────────────────────────┤
│            物理层                                            │
│   ESP32-S3 板 × N · USB Hub(可控电) · USB 继电器板 · 编译机    │
└─────────────────────────────────────────────────────────────┘
```

数据流（单次闭环）：

```
Jira 缺陷单 ──▶ ReproPlanner(生成复现步骤) ──▶ HardwareController+SerialMonitor
                                                            │
                                                       原始 log + coredump
                                                            │
                                            Symbolizer ──▶ 符号化 log
                                                            │
                                          Diagnostician(结合代码+知识库) ──▶ 诊断报告
                                                            │
                                              Fixer(产 patch, 开 MR)
                                                            │
                                              ══ HUMAN GATE (人 review MR) ══
                                                            │
                                          Builder(idf.py build) ──▶ Flasher(esptool)
                                                            │
                                              HardwareController ──▶ 复测
                                                            │
                                          Verdict(判定通过/失败) ──▶ 失败则回退
                                                            │
                                Summarizer ──▶ KnowledgeStore 沉淀 + 回写 Jira
```

---

## 1.5 部署拓扑与 MCP 化（双 VPS 实情）

确认的拓扑：**板子物理插在 Windows 上，开发/编译/烧录在 Windows 本地做；这台 Oracle Ubuntu VPS 主要跑智能体编排**。

> **tailscale 不进架构**：它只是家用原型阶段的网络后端。网络可达性抽象成"可配 bind host + 自包含鉴权"，代码不绑任何隧道——家用走 tailscale，公司走内网/VPN，代码不变只换部署。公司环境不能靠 tailnet 身份，故鉴权必须自包含（bearer token 为底线，公司上 mTLS）。

核心矛盾与解法：烧录/串口/按键是**本地 USB 操作**，只能贴着板子（Windows）执行；而智能体/编排可能在 VPS、Windows、或同事的任意机器上；且 **Windows 不 24h 在线**。解法是——

> **把执行层做成两层 MCP server：VPS 上常驻"控制面"，Windows 上按需"硬件网关"，中间用注册中心 + 调度器粘合。**

工具按可用性约束分两类（这是整个拆分的关键）：
- **hardware-bound**（flash / serial_capture / button / power_cycle / symbolize）：必须贴板子，**只能存在于硬件网关**，搬去 VPS 是空壳。
- **logic-bound**（git_pr / jira_* / kn_search / build）：纯软件，**放 24/7 的 VPS 控制面**，多人随时共用。

```
┌─ VPS（24h 在线 · 控制面 / 唯一入口）─────────────────────┐
│  control-plane MCP server:                               │
│   • logic-bound tools: git_pr / jira_* / kn / build       │ ← 任意人随时可用
│   • Registry:   硬件网关注册表（谁在线？能力？）           │
│   • Dispatcher: 硬件请求路由到在线网关                     │
│   • Queue:      网关离线时排队，上线后续跑                  │
│   • Orchestrator(LangGraph) + Agents + 知识库(RAG)        │
└──────────────▲ 可达网络（家用=tailnet / 公司=内网·VPN）────┘
               │ 注册/心跳 + RPC（bearer token / mTLS）
┌─ Windows（按需在线 · 硬件网关）──────────────────────────┘
│  hardware-gateway MCP server (ephemeral):                │
│   flash / serial_capture / button_press / power_cycle    │ ← 只有贴板子才存在
│   symbolize                                              │
│   开机→向 VPS 注册+心跳；关机→VPS 标离线                   │
│  直连: ESP32-S3(USB) / 继电器                             │
└──────────────────────────────────────────────────────────┘
   将来每个站点/每块板 = 一个独立硬件网关，统一注册进 VPS 控制面
```

这套设计如何化解约束：
- **Windows 不 24h**：硬件网关按需上线，开机注册、关机标离线；硬件请求在网关在线时路由，离线时**排队**或回 `hardware-offline`，上线后续跑。
- **多人共用**：所有人（同事的智能体）只对接 VPS 控制面这一个入口；逻辑操作立即可用，硬件操作由控制面透明路由到当前在线网关，同事无需知道板子在哪。
- **可扩展**：将来多板/多站点，每站一个硬件网关注册进来，控制面统一调度成"板资源池"。
- **编排半自动休眠**：流水线里只有 `flash/retest` 段必须等 Windows 在线。编排可跑到"诊断完、patch 待烧"就在 VPS 挂起（停人工门 + 硬件门），Windows 上线、PR 通过后续跑。

部署自由：智能体将来可在 arm-VPS / 本地 Windows / 本地 Ubuntu，统一经 MCP 接控制面。**M0 即把硬件网关做成网络化 MCP server**（streamable-http，bind host 可配 + bearer token，公司可上 mTLS）：家用原型经 tailscale、公司经内网/VPN，**代码不变**。本地 Windows agent 与远程 agent 从第一天就都是它的 client，板级锁防并发冲突；M2/M3 再加 VPS 控制面、注册中心、分布式队列与多用户鉴权。

> 编译（Builder）：属 logic-bound，个人测试在 Windows 本地跑（Docker Desktop + `espressif/idf`，或直接 IDF）；成熟后并入 VPS 控制面或独立编译服务供多 agent 共用。

## 2. ESP32-S3 关键事实与利用点

- **USB-Serial-JTAG（GPIO19/20）**：S3 自带，一根 USB 线即可同时完成 烧录 + UART log + JTAG 调试，无需外接 CH340/CP2102。测试台大幅简化。
- **复位与进入 bootloader**：`esptool` 通过 DTR/RTS 自动控制 EN/BOOT 引脚，烧录与软复位不需要继电器。继电器仅用于**冷启动 / 上电时序 / 按键 / 模拟插拔**这类 esptool 管不到的动作。
- **崩溃信息**：panic handler 打印 backtrace（地址）；coredump 可配置写到 flash 或 UART，用 `espcoredump.py` 解析。**符号化是必备基础设施**，模型读不懂裸地址。
- **多板识别**：`/dev/ttyUSBx` 会漂移，必须用 udev 规则按 USB 路径固定成 `/dev/autotest/boardA` 等稳定别名。

---

## 3. 硬件测试台（简单物理动作档）

选定形态：**1 台测试主机 + USB Hub（可控电）+ USB 继电器板 + N 块 ESP32-S3 板**。

| 物理动作 | 实现方式 |
|---|---|
| 冷启动 / 上电时序 | `uhubctl` 对支持 per-port power switching 的 hub 断电/上电；或继电器切板子供电 |
| 复位（软） | `esptool` 的 RTS/DTR，或一条串口命令 |
| 按键（USER/BOOT/自定义） | USB 继电器板的一路并接到物理按键两端，闭合 = 按下 |
| 串口插拔模拟 | `uhubctl` 对该端口 disable/enable |
| （可选）电流监测 | INA226 等通过 I²C 读，用于电源类 bug |

> 抽象成统一的 `HardwareController`，对上层只暴露 `press_button / power_cycle / reset / port_disable` 等动作，具体继电器型号与 uhubctl 命令藏在实现里，方便以后换硬件。

---

## 4. 组件清单与职责

### 4.1 工具层 `tools/`

| 组件 | 职责 | 关键接口 |
|---|---|---|
| `DeviceManager` | 板子注册表：USB 路径、串口别名、继电器通道映射；健康检查 | `get_board(id)` |
| `HardwareController` | 执行物理动作 | `press_button(board, btn, ms)` `power_cycle(board, delay_s)` `reset(board)` |
| `SerialMonitor` | 抓 UART，落盘带时间戳 log；监听 panic/coredump 触发；可注入串口命令 | `capture(board, until=cond)` `inject(board, line)` |
| `Symbolizer` | backtrace/coredump → 函数名+行号（addr2line / espcoredump） | `symbolize(elf, raw) -> str` |
| `Builder` | 容器/编译机上 `idf.py build`，产出 `.bin` + `.elf`，记录版本号 | `build(ref) -> artifacts` |
| `Flasher` | `esptool write_flash` 到指定板子 | `flash(board, bin)` |
| `JiraClient` | 拉缺陷单与复现步骤、回写状态/评论/附件 | `get_issue(id)` `comment(id, text)` |
| `GitClient` | clone / 切分支 / commit / push / 开 PR（GitHub）；产出 diff 供人 review | `propose_patch(diff) -> pr_url` |
| `KnowledgeStore` | RAG：写入案例、按语义召回相似历史案例 | `add(case)` `search(query, k)` |

### 4.2 智能体层 `agents/`

每个 agent 是"系统提示 + 受限工具集 + 结构化输出"，由编排层按阶段调用。

| Agent | 输入 | 输出（结构化） |
|---|---|---|
| `ReproPlanner` | Jira **结构化复现字段** + 知识库召回 | `ReproPlan{ actions[], serial_cmds[], success_criteria, max_attempts }` |

> 复现步骤是 Jira 结构化字段（已确认），ReproPlanner **直接解析字段**，无需 LLM 抽取自由文本——这一步确定性高、成本低、可单测。LLM 只在"字段→硬件动作/串口命令映射"和"召回历史相似案例"时介入。
| `Diagnostician` | 符号化 log + coredump + 相关源码 + 召回案例 | `Diagnosis{ root_cause, suspect_files[], confidence, evidence[] }` |
| `Fixer` | 诊断 + 相关源码 + 周边测试 | `Patch{ file_diffs[], rationale, risk_level }`（risk_level 决定是否强制人工门） |
| `Summarizer` | 整次闭环留痕 | `Case{ symptom, root_cause, fix, repro, lessons }` 入知识库 + Jira 评论 |

### 4.3 编排层 `orchestrator/`

LangGraph 状态机。节点 = 阶段，边 = 成功/失败/人工分支。

```
intake → plan_repro → execute_repro → capture_log → symbolize
  → diagnose → propose_fix → ══HUMAN GATE══ → build → flash
  → retest → verdict ──(fail)──▶ diagnose  (回退，限 N 次)
                         └─(pass)──▶ summarize → kn_deposit → close
```

- **人工门实现**：`propose_fix` 产出 MR 后，编排暂停，轮询 MR 状态（approved/merged）或等待飞书审批回调；通过才进 `build`。
- **重试上限**：retest 失败回退诊断的次数硬上限（如 3 次），超限标红转人工。
- **可恢复**：每阶段产出物持久化（artifact store），任意阶段崩溃可从断点续跑。

---

## 5. 技术选型

| 维度 | 选型 | 理由 |
|---|---|---|
| 编排 | LangGraph (Python) | 显式状态图、检查点、人工中断原生支持，契合"人工门" |
| Agent 模型 | Claude（主力 Sonnet，复杂诊断 Opus） | 长上下文读 log+源码；模型 id/定价需用时按 claude-api 参考核最新 |
| 串口 | pyserial | 事实标准 |
| 继电器/HUB | uhubctl + USB 继电器（具体型号见 §3） | 简单物理动作够用 |
| 编译 | Docker `espressif/idf` 镜像 on 编译机 | 环境隔离、可并行、版本固定 |
| 烧录 | esptool.py | 官方 |
| 知识库 | Qdrant 或 Chroma + embedding | RAG 召回历史案例 |
| 缺陷 | Jira REST（结构化复现字段，直接解析） | 解析确定性高、可单测 |
| 代码 | GitHub（PR，经 `gh` CLI） | 走 PR = 天然留痕 + 原生 review 门 |
| 人工门 | PR review + 飞书审批（lark-approval） | 审批通过回调驱动编排继续 |
| 工具暴露协议 | **MCP**（MCP server 暴露能力，agent/client 调用） | 工具与智能体解耦、可跨机/多人复用；M0 先 stdio，成熟切 streamable-http over tailscale |

语言：**Python** 贯穿（编排/工具/agent），与 LangGraph、pyserial、esptool 一致，生态最顺。

---

## 6. 目录结构

```
autotest_iot/
├── docs/ARCHITECTURE.md        # 本文件
├── orchestrator/               # LangGraph 状态机
├── agents/                     # 4 个 agent 定义
├── tools/
│   ├── hardware/               # DeviceManager, HardwareController(relay/uhubctl)
│   ├── serial/                 # SerialMonitor, Symbolizer
│   ├── build/                  # Builder, Flasher
│   ├── jira/                   # JiraClient
│   ├── git/                    # GitClient
│   └── knowledge/              # KnowledgeStore (RAG)
├── config/                     # 板子注册表、udev、env、prompt 模板
└── tests/                      # 工具层单测（每个工具必须可单测）
```

---

## 7. 安全与治理边界

- **最小权限**：Git token 只给目标仓库、限分支；Jira token 只给读写评论/附件。
- **沙箱编译**：编译在容器内，禁止访问生产网。
- **diff 强制 review**：所有 patch 走 MR，禁止直推 main/develop（GitFlow）。
- **动作白名单**：HardwareController 只允许预定义动作，模型无法构造任意 GPIO 操作。
- **烧录隔离**：只对注册的测试板烧录，串口别名锁定，杜绝烧错板。

---

## 8. 分期路线

| 阶段 | 目标 | 验收 |
|---|---|---|
| **M0 基础设施** | 串口固定、build/flash/monitor 跑通、日志落盘 + 符号化脚本、继电器点得动 | 手动跑通一次 build→flash→抓 log→符号化 |
| **M1 半自动复现** | 人写复现步骤 → 智能体执行硬件动作 + 抓 log → Diagnostician 给诊断报告 | 给定稳定可复现 bug，自动产出诊断 |
| **M2 修复辅助** | Fixer 产 patch → MR → **人 review 合并** → 自动 build+flash → 自动复测 | 修复经人确认后自动闭环 |
| **M3 闭环** | 全流程自动，仅高风险动作用飞书审批确认；失败回退人工 | 端到端无人值守跑通（人在环上不在环里） |
| **M4 知识沉淀** | 每次闭环产出结构化案例入 RAG → 下次诊断召回复用 | 新单命中历史案例，复现/诊断提效 |

**MVP = M0 + M1**：证明"硬件闭环 + log 诊断"可行，再谈自动修复。不要一上来追求全自动。

---

## 9. 关键风险与对策

| 风险 | 对策 |
|---|---|
| 嵌入式 bug 复现率低（时序/射频/电源） | 显式定义"复现成功"判定（连续 N 次未触发 panic 等）；接受 <100%，超限转人工 |
| 模型幻觉改坏代码 | patch 强制 MR review；risk_level 分级；不直推 |
| 烧错板 / 串口漂移 | udev 固定别名；Flasher 只认注册板 |
| 多板资源争抢 | DeviceManager 串行/排队；编译容器隔离 |
| 全流程 token 成本 | log 先符号化+裁剪再喂模型；用知识库召回替代全量读码；Sonnet 主力 |

---

## 10. 尚需补齐的边界信息

已确认（2026-06-13）：
- [x] **代码服务器**：GitHub → GitClient 走 `gh` CLI 开 PR，review 即人工门
- [x] **Jira 复现信息**：结构化字段 → ReproPlanner 直接解析，不抽自由文本
- [x] **编译环境**：Docker `espressif/idf` 镜像
- [x] **固件配合度**：能埋测试模式 → 加串口命令通道（如 `test> ` 前缀），自动化难度最低

仍待补（接入前/配置期收集，多为自由文本或密钥，不阻塞 M0 工具层开发）：
- [ ] ESP-IDF 版本号（决定 `espressif/idf:vX.Y` 镜像 tag；Windows 上已按 wiki 装好，确认版本即可）
- [ ] 测试模式串口命令协议（先占位，M1 固化进固件后导出命令清单 → 配置成可注入动作白名单）
- [ ] 控电方案：单板，初期可不做 per-port 控电；若需冷启动用继电器切板子供电即可
- [ ] Jira field id / GitHub PAT / 目标 repo（初期用本地 mock Gitea + 假 Jira，不接公司真实系统）
- [ ] 历史缺陷库：初期从零累积，不冷启动

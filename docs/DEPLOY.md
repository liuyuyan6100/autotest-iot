# 真实环境部署指南

把 autotest_iot 跑在真公司系统上（真 Jira / GitHub / 飞书 / ESP32-S3 板）的逐步配置与验证清单。
架构与设计见 [`ARCHITECTURE.md`](ARCHITECTURE.md)；本文只讲"怎么配、怎么验、怎么排错"。

---

## 0. 拓扑回顾

```
[VPS / 公司内网服务器]  控制面（24h，唯一入口，port 8788）
        ▲ MCP / HTTP
        │ 注册+心跳
[Windows 实验室机]  硬件网关 M0 server（port 8787）── USB ── ESP32-S3 板 + 继电器
```

- **家用原型**：VPS↔Windows 经 tailscale；`host` 填 tailscale IP。
- **公司**：不走 tailscale，`host` 填内网/VPN IP + bearer token +（建议）mTLS。
- Windows 不 24h：按需上线注册、关机 TTL 超时标离线，请求离线入队、上线续跑。

---

## 1. 前置依赖

| 依赖 | 装在哪 | 用途 |
|---|---|---|
| Python ≥ 3.11 | 两台 | 主程序 |
| git | 两台 | 代码 |
| Docker Desktop | Windows | 编译固件（`espressif/idf` 镜像）；无 Docker 可 `builder_backend: local` 直调 `idf.py` |
| ESP-IDF 工具链 | Windows | 产生 `xtensa-esp32s3-elf-addr2line`（符号化 backtrace） |
| `gh` CLI（已 `gh auth login`） | 跑 Fixer/PR 检查的机器 | 开 PR、查 PR 是否合并 |
| （可选）`uhubctl` + USB 继电器 | Windows | 冷启动/控电/按键 |
| ESP32-S3 板 + USB 线 | Windows | 被测设备 |

---

## 2. 获取代码 + 安装

```bash
git clone https://github.com/liuyuyan6100/autotest-iot.git   # 或 gitee
cd autotest-iot
python3 -m venv .venv && . .venv/bin/activate                # Windows: .venv\Scripts\activate
pip install -e ".[test]"
pytest -q                                                     # 应全绿（无硬件/无 key 也能过）
```

---

## 3. 必填配置速查（一张表）

复制 `config/boards.yaml.example` → `config/boards.yaml`（已被 gitignore，不入库），按下表填。
敏感项优先用**环境变量**，避免落盘。

| 配置项 / 环境变量 | 在哪 | 来源 / 说明 |
|---|---|---|
| `boards.boardA.port` | boards.yaml | Windows 的 COM 口（设备管理器看）/ Linux 的 udev 别名 |
| `boards.boardA.baud` | boards.yaml | 通常 115200 |
| `server.host` / `server.port` / `server.token` | boards.yaml | 硬件网关 bind；token 或 `AUTOTEST_TOKEN` |
| `tools.idf_version` | boards.yaml | 决定 `espressif/idf:<tag>`，与你装的 IDF 一致（如 v5.3） |
| `tools.addr2line` | boards.yaml | 留空自动发现；找不到就填全路径 |
| `tools.builder_backend` | boards.yaml | `docker` 或 `local` |
| `agents.model` / `effort` | boards.yaml | 默认 `claude-opus-4-8` / `high` |
| `agents.test_command_whitelist` | boards.yaml | 固件测试模式命令前缀，**安全门** |
| `control_plane.host/port/token` | boards.yaml | 控制面；token 或 `AUTOTEST_CP_TOKEN` |
| `control_plane.ttl` | boards.yaml | 网关心跳超时（秒） |
| `gateway_reg.cp_url/cp_token/id/boards` | boards.yaml | 网关注册到控制面 |
| `mcp.url` / `mcp.token` | boards.yaml | agent/编排器接控制面的地址 |
| `jira.backend` | boards.yaml | `rest`（真实）或 `mock` |
| `jira.base_url/email/token` | boards.yaml 或 env | Jira Cloud；token 用 `JIRA_EMAIL`/`JIRA_TOKEN` |
| `jira.repro_field` | boards.yaml | 存结构化复现步骤的自定义字段 id（可选） |
| `feishu.approval_code` | boards.yaml | 飞书后台审批流程 code（必填，启用飞书门时） |
| `feishu.app_id/app_secret` | boards.yaml 或 env | `LARK_APP_ID`/`LARK_APP_SECRET` |
| `feishu.approver_open_id` | boards.yaml | 审批人 open_id |
| `ANTHROPIC_API_KEY` | 环境变量 | LLM（编排器侧） |

---

## 4. 逐步配置与验证

每步都给了一个**验证命令**——绿了再下一步，避免最后才发现问题。

### A. 板子与硬件（Windows）

- 插板子，设备管理器看 COM 口，填 `boards.boardA.port: COMx`。
- （可选）继电器接按键/供电，`buttons.*.relay` / `power_relay` 填继电器通道。

```bash
# 验证：列出板子，online=true
python -m autotest_mcp.server &          # 起网关（另开终端）
# 或用 MCP client 调 list_boards；最快验证见 B
```

### B. 编译 + 烧录 + 符号化（Windows，无需 Jira/LLM）

- 确认 `tools.idf_version` 与本机 IDF 一致；`tools.addr2line` 留空让其自动发现。
- 准备一个能构建的 IDF 工程（可主动 `abort()` 触发 panic 便于验证符号化）。

```bash
# 验证：build → flash → capture → symbolize 一条龙（手动调 MCP 工具或脚本）
# 关键：symbolize 能把 Backtrace 地址还原成 函数名+文件:行
```

### C. 控制面（VPS）

```bash
export AUTOTEST_CP_TOKEN=...
python -m autotest_mcp.run_control_plane
# 验证：curl -H "Authorization: Bearer $AUTOTEST_CP_TOKEN" http://<vps>:8788/gateways → []
```

### D. 硬件网关（Windows）+ 注册

```bash
python -m autotest_mcp.server                    # M0 网关
python -m autotest_mcp.run_gateway_register      # 注册+心跳到控制面
# 验证：控制面 GET /gateways 出现该网关，online=true
```

### E. 缺陷源：真 Jira

- 飞书/Jira 后台拿 API token；填 `jira.backend: rest` + base_url + email + token。
- 复现步骤若存在自定义字段，填 `jira.repro_field`（字段值应为 `[{action,target,note}]` 结构）。

```bash
# 验证：取一个真缺陷（mock 时 defects_path 仅 mock 用，rest 时忽略）
JIRA_EMAIL=you@co.com JIRA_TOKEN=... python -c "
from autotest_mcp.config import load_config
from autotest_mcp.defects.jira import make_jira
cfg=load_config('config/boards.yaml'); cfg.jira.backend='rest'
print(make_jira(cfg).get_defect('PROJ-123').model_dump())
"
```

### F. 代码：GitHub

```bash
gh auth status                       # 验证已登录
# 验证 PR 合并检查（对一个已知 PR）：
python -c "from autotest_mcp.git_client import GithubPrChecker as G; print(G().is_merged('https://github.com/OWNER/REPO/pull/1'))"
```

### G. 飞书审批门（启用时）

- 飞书开放平台建自建应用，开通审批相关 scope（`approval:instance` 等）。
- 后台创建审批流程，拿 `approval_code`；填 app_id/app_secret/approver_open_id。
- 注意：lark-cli 的 approval 模块无"创建实例"命令，本系统走 OpenAPI（`POST /approval/v3/instances`）。

```bash
# 验证：能换 tenant_access_token（用注入 http 或直接跑一次 driver 配 FakeGate 先通路）
```

### H. LLM

```bash
export ANTHROPIC_API_KEY=...
python -c "import anthropic; print(anthropic.Anthropic().messages.create(model='claude-opus-4-8',max_tokens=16,messages=[{'role':'user','content':'ping'}]).stop_reason)"
```

### I. 知识库（可选）

- 默认 `FileKnowledgeStore`（JSON 文件，无依赖）。生产要更强召回装 `pip install -e ".[vector]"` 用 chromadb。
- 跑闭环时 `--kb /path/kb.json` 启用召回+沉淀。

---

## 5. 端到端跑

```bash
# VPS/编排机上（agent 以 VPS 为主）
export ANTHROPIC_API_KEY=...
export JIRA_EMAIL=... JIRA_TOKEN=...
python -m autotest_mcp.run_orchestrate PROJ-123 \
  --source <固件仓库目录> --gate feishu --kb /path/kb.json
```

流程：取 Jira 缺陷 → ReproPlanner → 经控制面调硬件网关复现 → 符号化 → Diagnostician →
Fixer 开 PR → **飞书审批门**（通过→rebuild+flash+复测；拒绝→rejected 终态）→
复测 pass 则 Summarizer 沉淀知识库。

---

## 6. 验证检查点（逐条对齐）

- [ ] `pytest -q` 全绿
- [ ] 控制面 `GET /gateways` 能看到在线网关
- [ ] `make_jira(...).get_defect(...)` 返回真缺陷
- [ ] `GithubPrChecker.is_merged(...)` 返回正确
- [ ] 飞书能换 tenant_access_token
- [ ] `ANTHROPIC_API_KEY` 能正常 messages.create
- [ ] `run_orchestrate` 能跑到人工门并暂停（feishu 创建审批）

---

## 7. 常见问题 / 排错

| 现象 | 排查 |
|---|---|
| 板子 online=false | COM 口错 / 被占用（关掉其他串口监视器）/ 权限（Linux 加 dialout 组） |
| `addr2line not found` | 设 `tools.addr2line` 为 IDF 工具链里的全路径，或确保 `$IDF_PATH/tools` 在 PATH |
| 编译失败 | 镜像 tag 与本机 IDF 不一致；或 Windows Docker 未共享驱动器卷；换 `builder_backend: local` |
| 控制面看不到网关 | `gateway_reg.cp_url` 不通 / token 不匹配 / Windows 防火墙挡了端口 |
| 实验室网络不通 tailscale | 改走公司内网/VPN；`host` 填内网 IP，开 mTLS |
| 飞书创建审批 401/403 | app_id/secret 错 / scope 未开通 / approval_code 无效 |
| Jira 401 | email:token 的 basic auth；token 是 API token 不是密码 |
| LangGraph `unregistered type` 警告 | 非阻塞；生产换持久 checkpointer 时按提示注册 state 的 pydantic 类型 |
| 复测一直 fail | 真的没修好；状态机会重试到 `max-attempts` 后转 `escalated`，人工介入 |

---

## 8. 安全与回滚

- **人工门始终在**：所有代码 patch 走 PR + 飞书审批，不自动合并；拒绝即终止。
- **串口命令白名单**：ReproPlanner 注入的命令必须命中 `agents.test_command_whitelist`，非白名单被拒并留痕。
- **最小权限 token**：Jira token 只给目标项目读写评论；GitHub PAT 限仓库限分支；用完即轮换。
- **公开仓库注意**：本仓库目前公开，`config/boards.yaml`/`.env` 已 gitignore，切勿把真实 token 提交；如含公司敏感架构，建议转私有。
- **可回滚**：知识库只沉淀复测**通过**的案例（失败不沉淀，不污染）；PR 可 revert；固件可回烧旧版本。

---

## 9. 常用命令速查

```bash
# 控制 / 网关
python -m autotest_mcp.run_control_plane        # VPS 起控制面
python -m autotest_mcp.server                   # Windows 起硬件网关
python -m autotest_mcp.run_gateway_register     # 网关注册+心跳

# 编排（主入口）
python -m autotest_mcp.run_orchestrate BUG --source <仓库> --gate feishu --kb kb.json
python -m autotest_mcp.run_orchestrate BUG --fake --source /tmp/fw --gate auto   # 无 key/无板调试

# 分阶段
python -m autotest_mcp.run_m1 BUG --fake        # 仅复现+诊断
python -m autotest_mcp.run_m2 BUG --fake --source /tmp/fw --kb kb.json   # +修复+复测+沉淀

# 知识库
python -m autotest_mcp.run_m3 --kb kb.json search "按键 panic"
python -m autotest_mcp.run_m3 --kb kb.json show

# 双推（origin + gitee）
./scripts/push-all.sh
```

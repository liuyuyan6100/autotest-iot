# autotest_iot 落地路线图（ROLLOUT）

> 目标:把现在跑在 fake/mock 上的代码,逐层换成真硬件、真接口、真 LLM、真网络,直到全链路在真实环境闭环。
>
> 代码已全部写完(M0–M3 + 编排 + 控制面 + 飞书门 + 真 Jira/Git 接口,77 测试全绿)。这份文档**只管"把假的换成真的"**。

---

## 怎么用这份文档(给人 + 给 LLM)

### 给人

- 做完一个子任务,把 `- [ ]` 改成 `- [x]`(或直接在 GitHub/Gitee 网页上点勾)。
- 每一步都有 **完成定义(DoD)**——DoD 全满足才算这一步完成,不要只勾命令跑过。

### 给 LLM(关键)

> **当你说"下一步做什么"时,LLM 读这份文档,从上往下找第一个 `[ ]` 未勾选项,那就是当前该做的事。** 你不需要自己记进度——文档就是唯一事实来源。
>
> 所以:**改完状态记得提交**(LLM 只看仓库里的文件)。约定:勾项 ID 不变,只改 `[ ]`/`[x]`,不要重排顺序,否则历史参照会乱。

---

## 速查表

| 步骤 | 内容 | 在哪台机器 | 花钱吗 | 状态 |
|------|------|-----------|--------|------|
| **S1** | 本地 ESP32 环境 + panic demo 硬件闭环 | 实验室机(贴板) | 否 | `[ ]` |
| **S2** | M0 网关本地跑通(`localhost`,真板子) | 实验室机 | 否 | `[ ]` |
| **S3** | 真 Jira / Git / 知识库 接口逐个点亮 | VPS | 否 | `[ ]` |
| **S4** | 接真 LLM 跑 M1/M2 智能体 | VPS | **是(烧 token)** | `[ ]` |
| **S5** | 网络化 + 控制面 + 远程协同 | VPS + 实验室机 | 否 | `[ ]` |

> 顺序铁律:**S1(硬件根基)→ S2(本地闭环)→ S3(真接口)→ S4(真 LLM)→ S5(网络)**。
> S3 可在板子没到货时先做,与 S1/S2 解耦;**S5 必须最后**,它是"让已有的东西被远程用",不是价值本身。

---

## S1 · 本地 ESP32 环境(根基,先做)

**目标**:在贴板子的机器上,**不依赖本项目任何代码**,手动跑通一次 `build → flash → 抓串口 → 符号化`。
**前置依赖**:一块 szpi-esp32s3 板子、一根 USB 线、贴板的机器(建议 Windows 实验室机)。
**示例工程**:`examples/panic_demo/` —— 烧录后故意崩溃,产出 4 层干净 backtrace。

> Windows 实验室机推荐**官方 ESP-IDF 安装器**(原生),不要用 Docker——COM 口透传进 Windows 容器很麻烦。Docker 路径更适合 VPS/Linux 上做无板编译。

- [ ] **S1.1** 装 ESP-IDF v5.3(与 `builder.py` 的 `espressif/idf:v5.3` 对齐):官方 Tools Installer
      `https://docs.espressif.com/projects/esp-idf/en/v5.3/esp32s3/get-started/`
- [ ] **S1.2** 确认工具链就位:`idf.py --version` 能跑;`xtensa-esp32s3-elf-addr2line` 在 PATH 里(`where xtensa-esp32s3-elf-addr2line` 或 `which`)
- [ ] **S1.3** 设 target + 编译 panic demo:
      ```
      cd examples/panic_demo
      idf.py set-target esp32s3
      idf.py build
      ```
      产物应有 `build/panic_demo.elf`、`build/panic_demo.bin`、`build/flash_args`
- [ ] **S1.4** 烧录 + 看串口(替换为实际 COM 口,设备管理器查 USB JTAG/serial):
      ```
      idf.py -p COM5 flash monitor
      ```
      期望看到:`panic_demo: about to crash in 1s...` → 1 秒后 `Guru Meditation Error: Core 0 panic'ed (StoreProhibited)` + `Backtrace: 0x... 0x... 0x... 0x...`
- [ ] **S1.5** 手工符号化(把 Backtrace 那行地址粘进来):
      ```
      xtensa-esp32s3-elf-addr2line -pfiaC -e build/panic_demo.elf 0x4037xxxx 0x4037xxxx 0x4037xxxx 0x4037xxxx
      ```
- [ ] **S1.6** 把板子信息回填到 `config/boards.yaml`:COM 口、baud、(若有)继电器通道

**完成定义(DoD)**:第 S1.5 步的 addr2line 输出里能看到 `trigger_crash / step_two / step_one / app_main` 四个函数名。
**卡点速查**:
- 串口没输出 → 换 baud(默认 115200)、确认 USB 是数据线不是充电线、换 COM 口号
- 烧不进去 → 板子没进下载模式(szpi 用 USB-Serial-JTAG 一般自动进);按住 BOOT 再按 RST
- addr2line 全是 `?? ` → 用错 ELF(必须用 panic_demo.elf,不是别的工程),或地址粘错

---

## S2 · M0 网关本地跑通(`localhost`,真板子)

**目标**:用本项目的 M0 server,自动跑通 S1 那条链路(不再手敲 idf.py)。先不碰网络。
**前置依赖**:S1 全部勾完。

- [ ] **S2.1** 填好 `config/boards.yaml`(板子 COM 口等)+ 设 token(`AUTOTEST_MCP__TOOLS_TOKEN` 或 config 里);`server.transport` 设 `http`(本地调试可设 `stdio`)
- [ ] **S2.2** 装本包依赖:`pip install -e .`(含 mcp / esptool / pyserial …)
- [ ] **S2.3** 起本地网关(传输方式由 config `server.transport` 决定,不是命令行参数):
      ```
      python -m autotest_mcp.server   # http 模式默认绑 server.host(本地填 127.0.0.1)
      ```
- [ ] **S2.4** 装一个 MCP client(本地 Claude Code 配 `http://localhost:8787` + token,或直接用 CLI)
- [ ] **S2.5** 依次调用 7 个 tool,验证真板子上能跑:`list_boards → build(panic_demo) → flash → capture_serial → symbolize`
- [ ] **S2.6** 验证 `capture_serial` 检出 panic(`panic_detected=true`),`symbolize` 返回 `trigger_crash` 等函数名

**完成定义(DoD)**:一次自动化调用跑通 build→flash→capture→symbolize,串口 log 落盘、panic 自动检出、backtrace 自动还原——全程不手敲 idf.py。
**卡点速查**:
- tool 列表空 → token 不对(401)、或 client 没带 `Authorization: Bearer`
- build 失败 → `builder.py` 默认 `docker` 后端,实验室机若用原生 IDF 改 config 为 `backend: local`
- flash/capture 报端口占用 → 别的 monitor 进程没退,先 `idf.py monitor` 关掉

---

## S3 · 真 Jira / Git / 知识库 接口逐个点亮

**目标**:把三块外围接口从 fake 切到真实现。脱离硬件,可在 VPS 上做,与 S1/S2 解耦。
**前置依赖**:无(板子没到货也能做)。

- [ ] **S3.1 · Jira**:填 `jira` config(`base_url / email / api_token`),用 `run_m1.py` 拉一个真缺陷单,确认 `Defect` 字段解析正确
- [ ] **S3.2 · Git/PR**:`gh auth login` 通;`GhGitClient` 开的 PR 能在 GitHub 上看到;`GithubPrChecker.is_merged` 对已合并 PR 返回 true
- [ ] **S3.3 · 知识库**:`run_m3.py` 沉淀一条 case 到 `FileKnowledgeStore`(JSON 文件);`recall_context` 对相似描述能召回它

**完成定义(DoD)**:三块接口都从 fake 实现切到真实现,且各自端到端验证过一次(真缺陷单被拉取、真 PR 被创建、真 case 被召回)。
**卡点速查**:
- Jira 401 → token 是 API token 不是密码;`email:token` 做 basic auth
- gh PR 没出 → 确认默认分支、repo 有写权限
- 召回为空 → 检查 store 的 JSON 是否落盘、query 关键词是否命中(CJK 用 2-gram)

---

## S4 · 接真 LLM 跑 M1/M2 智能体

**目标**:从 fake LLM 切到 `claude-opus-4-8`,用真实缺陷单跑 repro→diagnose→patch。
**前置依赖**:S2(要真板子抓真 log)+ S3(要真缺陷单/真 PR)。**从这里开始烧 token。**

- [ ] **S4.1** 配 `ANTHROPIC_API_KEY`;`llm.py` 切真实现(模型 `claude-opus-4-8`,adaptive thinking,effort:high)
- [ ] **S4.2** `run_m1.py` 跑一个真缺陷:智能体产出 `ReproPlan` + `Diagnosis`,诊断能自圆其说(根因指向具体函数/行)
- [ ] **S4.3** `run_m2.py` 跑修复:智能体产出 `Patch` + `FileEdit`,在真实仓库 apply 成功、开 PR
- [ ] **S4.4** 跑一次 `run_orchestrate.py --gate auto`:M1→人工门→复测→判断的全状态机走一遍

**完成定义(DoD)**:对一个真缺陷,智能体给出可自圆其说的诊断 + 能 apply 成功的 patch 草稿,且全链路状态机无异常终止。
**卡点速查**:
- 输出乱/不合规 → `messages.parse` 的 pydantic schema 没覆盖某字段,看 validation 报错补默认值
- token 烧太快 → 先用 `run_m1.py` 单步跑,别一上来跑全 orchestrate;effort 可临时调 medium

---

## S5 · 网络化 + 控制面 + 远程协同(最后)

**目标**:让 VPS 上的 agent 和实验室机的本地 agent 经控制面协同操控同一块板子。
**前置依赖**:S2(真板子本地闭环已通)。tailscale 仅家用;公司走内网/VPN + bearer + 可选 mTLS(代码不绑任何隧道)。

- [ ] **S5.1** M0 绑可达 IP(家用 tailscale 网卡 / 公司内网网卡),`host` 配好,token + 可选 mTLS 开
- [ ] **S5.2** VPS 起 `run_control_plane.py`(Registry / Dispatcher / 离线队列)
- [ ] **S5.3** 实验室机起 `run_gateway_register.py` 注册到控制面 + 心跳,确认 TTL 不掉线
- [ ] **S5.4** VPS agent 经控制面路由到实验室网关,真板子执行一次 build→flash→capture
- [ ] **S5.5** 验证跨进程板级锁:VPS agent 和本地 agent 同时 flash 同一块板,一方排队或返回 busy
- [ ] **S5.6** 验证离线续跑:实验室机短暂离线时请求入队,上线后自动续跑

**完成定义(DoD)**:VPS 远程 agent 与实验室本地 agent 都能经控制面调到板子,板级锁在跨进程并发下生效,网关短暂离线时请求不丢。
**卡点速查**:
- VPS 连不到网关 → bind host / 防火墙 / VPN;`Authorization` 头
- TTL 反复掉线 → 心跳间隔调小;检查网络抖动
- 锁没生效 → 确认两个 client 走的是同一控制面 → 同一网关(别绕过控制面直连)

---

## 附:常用命令速查

| 做什么 | 命令 |
|--------|------|
| 起本地网关 | `python -m autotest_mcp.server`(传输由 config `server.transport` 决定) |
| 跑 M1(复现+诊断) | `python -m autotest_mcp.run_m1` |
| 跑 M2(修复) | `python -m autotest_mcp.run_m2` |
| 跑 M3(知识库) | `python -m autotest_mcp.run_m3` |
| 跑全链路状态机 | `python -m autotest_mcp.run_orchestrate --gate auto` |
| 起控制面(VPS) | `python -m autotest_mcp.run_control_plane` |
| 网关注册(实验室) | `python -m autotest_mcp.run_gateway_register` |
| 跑测试 | `pytest -q` |
| 重生成框架图 | `/usr/bin/python3 scripts/gen_flow_png.py` |

> 推进过程中若发现文档与现实(命令/路径/字段)不符,以**真实代码**为准,并顺手把这份文档改对——它要始终保持可信。

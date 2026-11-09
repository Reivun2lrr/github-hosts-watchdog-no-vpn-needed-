# GitHub Hosts Watchdog

> 无需代理即可改善 GitHub 访问 · No VPN needed for everyday GitHub access

[中文](#中文) | [English](#english)

---

<a id="中文"></a>
## 中文

一次改 `hosts` 只能管用几天，IP 一失效又打不开 GitHub。**GitHub Hosts Watchdog** 是一套面向 Windows 的自动化访问自愈系统：定时从多个 DoH 源发现可用 IP，经 TLS 证书校验与 HTTPS 探测确认后安全写入 `hosts`，再由双层看门狗与访问健康巡检，让进程崩溃、系统睡眠唤醒、IP 在成功轮次之间失效等情况都能自动恢复。一次部署，长期免维护。

**适合谁**：国内网络下的 Windows 10 / 11 用户，需要长期稳定使用 `github.com`、`git clone` 与 raw 资源，且不想依赖代理。
**要做什么**：只需双击一次 `run-as-admin.bat`；之后 IP 失效、进程崩溃、睡眠唤醒都自动恢复，无需日常维护。
**如果这个工具帮你省了时间，欢迎点一个 Star**，让同样被 GitHub 访问折磨的人更容易找到它。

> 范围说明：本工具解决 **DNS 解析层面**的访问问题。若网络对全部 GitHub IP 实施 TLS/SNI 层干扰，`hosts` 方案无法恢复网页访问，程序会明确诊断而不是伪装成功。详见「注意事项」。

### 当前版本与下载

| 项 | 值 |
|---|---|
| 最新版本 | `v1.0.2` — 热路径自愈与连接稳定性迭代（2026-11-09） |
| 下载 | [Releases Latest](https://github.com/Reivun2lrr/github-hosts-watchdog-no-vpn-needed-/releases/latest) → `github-hosts-watchdog-v1.0.2.zip`，含 11 个文件，解压即用 |
| 上一版本 | `v1.0.1` 保留为回退版；`v1.0.0` 为初始版 |
| 源码 | `main` 分支 · MIT 许可 · 仅 Python 3 标准库，无第三方依赖 |

> 请走 Latest 链接下载：`v1.0.1` 附件是改进前的旧架构，不含热路径、两个附件 CDN 域名与一键直连工具。

### 核心功能

- **可信 IP 发现**：3 个 DoH 端点（阿里 / Cloudflare / 腾讯）＋ 内置候选池；每域名最多 14 个候选、12 并发。每个候选须通过 TCP 443 连接、TLS 证书校验（SNI）与 HTTPS 请求，并拒绝私有／保留地址，防止 `hosts` 投毒。
- **安全写入事务**：仅替换受管理标记区块内的 GitHub 条目，自动清理重复与失效条目，其余 `hosts` 内容逐行原样保留；写前备份（保留 10 份）、写后字节校验、异常时字节级回滚，保留原文件编码、换行符与 ACL。有效记录少于阈值时完全不改动并提示。
- **生效与验证**：刷新 DNS 缓存 → 核对系统解析结果 → HTTPS 访问验证。全程不启动浏览器、不显示网页；网页仅在你主动执行 `--open` 或双击 `open-github.bat` 时打开，显示时机完全由你控制。
- **手动入口**：`open-github.bat`（双击）或 `py -3 github_hosts_keeper.py --open`，用默认浏览器打开 `https://github.com`。后台任务、自启、看门狗一律不调用它。
- **双层看门狗**：内部 supervisor 以独立子进程执行每轮任务（单轮超时强杀、异常计数）；外部计划任务每 2 分钟巡检心跳，对失联、僵尸进程、旧版本自动清理并拉起，含每小时重启上限。
- **访问健康巡检**：supervisor 空闲时轻量探测 `github.com`，连续失败达阈值即触发一轮完整 IP 重探测，补上「成功轮次之间 IP 失效」的发现空窗。
- **无人值守运行**：随机抖动间隔刷新（默认 10–25 分钟，模板 20–60 分钟）、失败后缩短至 10 分钟、登录自启（最高权限、取消 72 小时上限、支持电池与补跑）、单实例互斥、日志轮转与状态记录。
- **命令行接口**：11 个命令（含手动入口 `--open`），退出码 0–5 区分成功、无可用记录、权限不足、写入失败、验证失败与配置错误。详见程序 `--help`。

### 工作原理与运行示例

```text
双击 run-as-admin.bat
   |  UAC 批准一次
   v
计划任务（最高权限 / 登录自启）
   |
   +-- supervisor（常驻）
   |     +-- 热路径线程：每 500 ms 检查当前 github.com IP
   |     |      失效 -> 实时验证备用 IP -> 单行改 hosts + 刷新 DNS（约 20 ms）
   |     +-- worker：每 10-25 min 全量探测 9 个域名（TLS 校验 + 整页 500 KB）
   |
   +-- watchdog 任务：每 2 min 查心跳 -> 失联则清理并拉起
```

实测输出节选（2026-11-09；程序状态行为中文，`...` 表示省略）：

```text
$ py -3 github_hosts_keeper.py --status
===== GitHub Hosts Keeper 状态 =====
  result                 : success
  message                : 更新成功: 9 条记录, 页面可访问
  verified_count         : 9
  supervisor 健康          : 是 (心跳 7s, PID 7684 存活)
  访问巡检                 : ok=True 连续失败=0 (连通 HTTP 200)
  ...
========================================

github_hosts_keeper.log
2026-11-09 21:21:26,495 [INFO] 热路径切换 20.27.177.113 -> 20.205.243.166 耗时 21.2ms (DNS 0.12ms, 实时验证 1 个候选, 原因: 连接超时)
```

### 目录结构

| 文件 | 说明 |
|---|---|
| `github_hosts_keeper.py` | 主程序（单文件，约 1700 行，仅 Python 标准库） |
| `config.json` | 随附的默认配置，可直接使用或按需修改 |
| `config.example.json` | 与默认配置一致的对照模板，用于改坏后恢复默认值 |
| `run-as-admin.bat` | 一键启动器：申请 UAC → 注册两个计划任务 → 交由无窗口守护进程接管 |
| `open-github.bat` | **唯一手动入口**：双击才用默认浏览器打开 GitHub；任何后台流程都不会调用它 |
| `quick-connect.bat` | 一键直连：后台触发一次看门狗巡检，再用默认浏览器打开 GitHub；桌面快捷工具为同一份文件的副本 |
| `README.md` | 本文件（中英双语，含快速开始、常见问题与代码结构导览） |
| `docs/PREREQUISITES.md` | 使用前提（系统、权限、网络、会话） |
| `docs/CONFIGURATION.md` | 配置要求：全部配置项、默认值与调优建议 |
| `LICENSE` | MIT 许可证 |
| `.gitignore` | 排除运行时产物与本机数据 |
| `CONTRIBUTING.md` | 反馈问题所需信息、提交改动前的自检清单与边界 |

运行时产物 `state.json`、`heartbeat.json`、`ip_pool.json`、`github_hosts_keeper.log`、`backups/` 由程序自动生成，不纳入版本控制。

### 性能与热路径架构

**测量口径**（本机直连、禁用代理，用 `curl --noproxy '*'` 实测）：

| 指标 | 定义 |
|---|---|
| TTFB | `curl %{time_starttransfer}`，发起到收到首字节 |
| 完整加载 | `curl %{time_total}` 且 `size_download >= 500000`（GitHub 首页约 525 KB） |
| 故障检测 | 热路径发现当前 hosts IP 不可用的耗时；TCP 连接 400 ms 超时即判死 |
| 切换事务 | 决定切换 → 单行改写 hosts → 校验 → DNS 缓存生效的墙钟时间 |
| 端到端恢复 | 故障检测 + 切换事务，即链路失效到新 IP 可供浏览器使用 |
| 全量单轮 | `discover()` 完成 9 个域名探测的耗时 |

**目标阈值**：故障检测 < 500 ms、切换事务 < 50 ms、**端到端恢复 < 500 ms**（以上三项为本机可控部分，实测可稳定达成）；TTFB P95 < 1.2 s、完整加载 P95 < 3.5 s（含跨境抖动余量）。

**优化前后对比**（2026-11-09 实测）：

| 指标 | 优化前 | 优化后 |
|---|---|---|
| 端到端恢复 | 约 6 分钟（2 min 巡检 × 2 次失败 + 3 min 冷却 + 96 s 全量探测） | **约 426 ms**（400 ms 检测 + 26.2 ms 切换，日志 `热路径切换 ... 耗时 26.2ms`） |
| 故障时浏览器表现 | `ERR_CONNECTION_TIMED_OUT`，8–20 s 超时 | 亚秒级自动切换 |
| 全量单轮 | 96 s（9 域名串行） | **31 s**（域名级并发；确定性基准 2721 → 612 ms，4.45×） |
| 切换事务 | 整块重建 + `ipconfig /flushdns` 子进程 | **26.2 ms**（单行增量替换 + Win32 DNS 刷新 7.12 ms） |
| TTFB / 完整加载 | 正常窗口 0.43–0.50 s / 1.07 s；故障时无响应 | 0.366–1.064 s / 1.019–3.029 s（8 次采样 **8/8** 完整成功，中位 0.418 s / 1.465 s） |

**架构**：supervisor 内常驻「热路径」线程，与慢速全量探测解耦。后台每 3 s 并发微探测内置候选池，维护 `ip_pool.json`（RTT 与失败计数）；每 500 ms 检查当前 `github.com` 记录，连接探测失败即从池中取排序候选**逐个实时验证**，只有此刻验证通过的 IP 才单行增量改写 hosts 并直接调用 Win32 DNS 刷新；候选全不通则判定网络层整体阻断，不改 hosts、退避等待，避免在失效 IP 之间空转。全量 `discover()` 降为池维护，仍负责其余 8 个域名与整页 500 KB 正文校验；worker 运行期间热路径暂停写 hosts（`CYCLE_RUNNING`）避免并发写冲突。所有候选 IP 同时不可达时进入 2 s 退避并节流日志，不产生无效连接风暴。400 ms 连接探测在链路抖动时会把偶发变慢的可用 IP 判死；切换后设 5 s 观察期并排除 10 s 内刚切离的 IP 抑制来回抖动，实测该窗口内浏览器访问仍 8/8 完整成功，切换不影响正在进行的页面加载。

**取舍与影响范围**：

- 跨境 TCP/TLS 握手本身约 250–450 ms，525 KB 页面传输另需 0.7–1.5 s，**TTFB 与完整加载无法做到个位/十位毫秒级**；「毫秒级」目标落在**本机可控的故障检测与切换**（分钟级 → 数百毫秒）。突破网络层下限需境内加速或合规代理，会改变「无需代理」定位，本次未引入。
- 所有候选 IP 同时被网络层阻断时（实测出现过），hosts 方案无法自愈，热路径退避等待链路恢复；这是物理边界，不是程序缺陷。
- 新增 `ip_pool.json` 运行时状态、`--hotpath-once` 命令与 `hotpath_*` 配置项；其余 CLI、日志、`state.json` / `heartbeat.json`、hosts 受管理区块、备份回滚、桌面工具、不自动打开网页的行为均保持不变。
- 热路径持续探测约 1–3 次/秒 HTTPS 请求；`hotpath_enabled: false` 可一键退回原定时架构。

### 代码结构导览

主程序是单文件、仅使用 Python 标准库。按现有函数分为五组，方便定位与审阅：

| 分组 | 代表函数 |
|---|---|
| IP 发现与探测 | `doh_query`、`public_ipv4`、`probe`、`discover` |
| `hosts` 事务与安全 | `decode_hosts`、`rebuild_hosts`、`backup_hosts`、`write_hosts_bytes`、`rollback`、`apply_hosts`、`flush_dns` |
| 自愈与状态 | `run_cycle`、`verify`、`access_check`、`run_watchdog`、`run_daemon`、`write_heartbeat`、`pid_alive` |
| 命令行与安装 | `install_task`、`uninstall_task`、`show_status`、`do_rollback`、`open_github_page`、`main` |
| 热路径与故障切换 | `micro_probe`、`refresh_pool`、`verify_and_switch`、`switch_domain_ip`、`hotpath_loop`、`_discover_one` |

自检入口（均无需额外依赖）：`--help` 列出全部命令；`--dry-run` 只探测不写文件；`--status` 只读查看状态；`--rollback` 还原最近一次 `hosts` 备份。

### 使用前提（摘要）

Windows 10 / 11；Python 3.x（**无需第三方库**）；首次运行需批准一次 UAC 以取得管理员权限；无需 Edge（程序不再启动浏览器，手动入口使用系统默认浏览器）；需要至少一个交互式登录会话；DoH 端点与 GitHub IP 需可达。完整清单见 [`docs/PREREQUISITES.md`](docs/PREREQUISITES.md)。

### 配置要求（摘要）

全部行为集中于 `config.json`，守护进程每轮热加载，改后无需重启。可调整刷新间隔范围、各类超时与重试、监控域名、DoH 端点、保护阈值、验证方式与看门狗参数；每项均有内置默认值，配置文件可整体省略。完整表格见 [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)，可复制模板见 `config.example.json`。

### 快速开始

1. 确认已安装 Python 3，把本目录放到一个稳定的本地路径。
2. 双击 `run-as-admin.bat`，在 UAC 弹窗点「是」。
3. 查看状态：

```bat
py -3 github_hosts_keeper.py --status
```

脚本自动注册计划任务并完成守护交接，**之后无需保留任何控制台窗口**；IP 探测、`hosts` 写入与 DNS 刷新都由程序完成。仅使用 Python 标准库，无需安装任何依赖。

### 验证

```bat
py -3 github_hosts_keeper.py --dry-run
py -3 github_hosts_keeper.py --status
```

`--dry-run` 只探测、不写任何文件，可用于安装前自检；`--status` 中「supervisor 健康: 是」且 `result: success` 表示当前可用；`--rollback` 可还原最近一次 `hosts` 备份。全部命令见 `py -3 github_hosts_keeper.py --help`。

提交问题或改动前，用程序自带命令自检即可，无需安装测试框架或第三方依赖：

| 命令 | 通过标准 |
|---|---|
| `py -3 github_hosts_keeper.py --help` | 11 个命令全部列出，无异常 |
| `py -3 github_hosts_keeper.py --dry-run` | 只探测、不写 `hosts`，退出码 0 |
| `py -3 github_hosts_keeper.py --status` | `result: success`、`supervisor 健康: 是` |
| `py -3 -m py_compile github_hosts_keeper.py` | 无语法错误 |
| `py -3 github_hosts_keeper.py --rollback` | 需要时能还原最近一次 `hosts` 备份 |

改了配置需确认 `config.json` 与 `config.example.json` 键集合一致；改了说明需同步本文件的中文与 English 两部分。

### 常见问题 / Troubleshooting

| 现象 | 怎么处理 |
|---|---|
| 首次运行弹出 UAC | 点「是」。用于注册计划任务和写入 `hosts`；之后后台运行不再弹窗。 |
| 出现蓝色权限窗口或控制台一闪而过 | 当前版本已统一隐藏派生进程窗口。若仍出现，确认运行的是本目录当前版本，再执行一次 `run-as-admin.bat`。 |
| 突然又打不开 GitHub | 执行 `py -3 github_hosts_keeper.py --once` 立即触发一轮重探测；访问健康巡检也会在连续失败后自动触发。 |
| 日志里出现「心跳过期」后自动恢复 | 睡眠唤醒后的补跑，属预期行为，无需干预。 |
| 改了 `config.json` 没生效 | 配置每轮热加载、无需重启；用 `--once` 立即跑一轮确认。 |
| 想手动打开 GitHub 网页 | 双击 `open-github.bat`，或执行 `py -3 github_hosts_keeper.py --open`。后台流程不会自动打开网页。 |
| 想还原被改动的 `hosts` | 执行 `py -3 github_hosts_keeper.py --rollback`。 |
| `hosts` 改了但浏览器仍打不开 | 先看下面「注意事项」的能力边界与网络配置：浏览器 DoH、系统代理、IPv6 优先都会绕过 `hosts`。 |

遇到问题请开 Issue，并附上 `--status` 输出与 `github_hosts_keeper.log` 中的相关片段；提交改动前请按 [`CONTRIBUTING.md`](CONTRIBUTING.md) 自检。

### 注意事项

- **能力边界**：只能解决 DNS 解析层面问题。TLS/SNI 层全量干扰、`DoH` 与候选池全部不可达时，`hosts` 无解，程序会保留原配置并明确诊断。
- **网络配置**：浏览器「安全 DNS / DoH」、系统或浏览器代理、VPN、IPv6 优先、网关强制 DNS 劫持都可能绕过 `hosts`；校园网与企业网策略差异较大，以本机验证为准。
- **运行条件**：关机或无交互式登录会话时不运行；睡眠期间暂停，唤醒后靠任务补跑（会看到「心跳过期」后自动恢复，属预期）。每小时重启上限为 3 次，超限只告警。
- **覆盖范围**：配置中的 9 个 GitHub 域名，包含 `objects.githubusercontent.com` 与 `release-assets.githubusercontent.com` 两个 Release 附件 CDN 域名（直连下载附件 / 头像，使用内置 Fastly 候选池、不走 DoH）；不含 SSH（`git@github.com:22`）与 IPv6。GitHub 登录态、2FA、组织 SSO 与私有仓库授权与本工具无关。
- **安全**：计划任务以最高权限运行本目录下的脚本，请确保脚本目录权限受控，防止被篡改后借道提权。仅使用程序内置来源并逐个验证的 IP，请勿混用来源不明的「hosts 一键包」。
- **合规**：仅用于改善对 GitHub 等合法站点的访问体验，请遵守所在单位的网络使用规定与相关法律法规。

---

<a id="english"></a>
## English

Editing `hosts` once only works for a few days — GitHub becomes unreachable again as soon as the IP changes. **GitHub Hosts Watchdog** is a self-healing access system for Windows: it periodically discovers usable IPs from multiple DoH sources, validates them with TLS certificate checks and HTTPS probes, safely writes them to `hosts`, and relies on a two-layer watchdog plus access-health checks to recover automatically from process crashes, sleep/wake cycles, and IPs that expire between successful refresh cycles. Deploy once, maintain nothing.

**For**: Windows 10 / 11 users on networks where GitHub access breaks intermittently, who need `github.com`, `git clone`, and raw assets to keep working without a proxy.
**What you do**: double-click `run-as-admin.bat` once. IP expiry, process crashes, and sleep/wake recovery are handled automatically from then on.
**If this saved you time, a Star helps others hitting the same GitHub access problem find it.**

> Scope: this tool solves access problems at the **DNS resolution** layer. If a network applies TLS/SNI-level interference to every GitHub IP, editing `hosts` cannot restore web access; the program reports this explicitly instead of pretending to succeed. See "Notes".

### Current Version & Download

| Item | Value |
|---|---|
| Latest | `v1.0.2` — hot-path failover and connection stability iteration (2026-11-09) |
| Download | [Releases Latest](https://github.com/Reivun2lrr/github-hosts-watchdog-no-vpn-needed-/releases/latest) -> `github-hosts-watchdog-v1.0.2.zip`, 11 files, extract and run |
| Previous | `v1.0.1` is kept as the rollback version; `v1.0.0` is the initial release |
| Source | `main` branch, MIT licensed, Python 3 standard library only, no third-party packages |

> Always use the Latest link: the `v1.0.1` asset predates the hot path, the two asset-CDN domains, and the one-click connect tool.

### Key Features

- **Trusted IP discovery**: 3 DoH endpoints (Alibaba / Cloudflare / Tencent) plus a built-in candidate pool; up to 14 candidates per domain, 12 concurrent probes. Each candidate must pass a TCP 443 connection, TLS certificate validation (SNI), and an HTTPS request; private/reserved addresses are rejected to prevent `hosts` poisoning.
- **Safe write transaction**: only the GitHub entries inside a managed marker block are replaced; duplicate and stale entries are cleaned while every other line of `hosts` is preserved verbatim. Backup before writing (10 retained), byte verification after writing, byte-level rollback on failure, with original encoding, line endings, and ACL preserved. If valid records fall below the threshold, `hosts` is left untouched with an explicit notice.
- **Activation and verification**: flush the DNS cache → confirm the system resolution → verify over HTTPS. No browser is launched and no page is displayed at any point.
- **Manual entry**: double-click `open-github.bat`, or run `py -3 github_hosts_keeper.py --open`, to open `https://github.com` in your default browser. No background task, autostart, or watchdog ever calls it — you control exactly when the page appears.
- **Two-layer watchdog**: an internal supervisor runs each cycle in a separate child process (hard timeout kill, failure counting); an external scheduled task checks the heartbeat every 2 minutes and cleans up / restarts lost, zombie, or legacy instances, with an hourly restart cap.
- **Access-health checks**: while the supervisor is idle it performs a lightweight `github.com` probe; consecutive failures trigger a full IP rediscovery cycle, closing the detection gap when an IP expires between successful cycles.
- **Unattended operation**: randomized jittered refresh (10–25 minutes by default; 20–60 in the template), shortened to 10 minutes after failure, logon auto-start (highest privileges, no 72-hour limit, battery- and catch-up-friendly), single-instance mutex, log rotation, and state recording.
- **CLI**: 11 commands (including the manual `--open` entry); exit codes 0–5 distinguish success, no usable record, insufficient privileges, write failure, verification failure, and configuration error. See the program's `--help`.

### How It Works & A Real Run

```text
double-click run-as-admin.bat
   |  one UAC approval
   v
scheduled tasks (highest privileges / logon autostart)
   |
   +-- supervisor (resident)
   |     +-- hot path: checks the current github.com IP every 500 ms
   |     |      failure -> live-verify a standby IP -> single-line hosts rewrite + DNS flush (~20 ms)
   |     +-- worker: full probe of 9 domains every 10-25 min (TLS check + 500 KB full page)
   |
   +-- watchdog task: heartbeat every 2 min -> clean up and restart if lost
```

Excerpt from a real run on 2026-11-09 (the program prints status in Chinese; `...` marks omitted lines):

```text
$ py -3 github_hosts_keeper.py --status
===== GitHub Hosts Keeper 状态 =====
  result                 : success
  message                : 更新成功: 9 条记录, 页面可访问
  verified_count         : 9
  supervisor 健康          : 是 (心跳 7s, PID 7684 存活)
  访问巡检                 : ok=True 连续失败=0 (连通 HTTP 200)
  ...
========================================

github_hosts_keeper.log
2026-11-09 21:21:26,495 [INFO] 热路径切换 20.27.177.113 -> 20.205.243.166 耗时 21.2ms (DNS 0.12ms, 实时验证 1 个候选, 原因: 连接超时)
```

### Project Structure

| File | Description |
|---|---|
| `github_hosts_keeper.py` | Main program (single file, ~1700 lines, standard library only) |
| `config.json` | Shipped default configuration, usable as-is or editable |
| `config.example.json` | Reference template identical to the defaults, for restoring them |
| `run-as-admin.bat` | One-click launcher: UAC → register both scheduled tasks → hand over to the windowless daemon |
| `open-github.bat` | **Only manual entry**: double-click to open GitHub in your default browser; no background flow calls it |
| `quick-connect.bat` | One-click direct connect: triggers one background watchdog check, then opens GitHub; the desktop shortcut is a byte-identical copy of this file |
| `README.md` | This file (bilingual: quick start, troubleshooting, code map) |
| `docs/PREREQUISITES.md` | Prerequisites (system, privileges, network, session) |
| `docs/CONFIGURATION.md` | Configuration reference: every key, default, and tuning advice |
| `LICENSE` | MIT License |
| `.gitignore` | Excludes runtime artifacts and local data |
| `CONTRIBUTING.md` | Issue reporting checklist, pre-submission self-checks, and contribution boundaries |

Runtime artifacts `state.json`, `heartbeat.json`, `ip_pool.json`, `github_hosts_keeper.log`, and `backups/` are generated automatically and are not version-controlled.

### Performance & Hot Path

**Measurement definitions** (direct connection, no proxy, measured with `curl --noproxy '*'`):

| Metric | Definition |
|---|---|
| TTFB | `curl %{time_starttransfer}`, request start to first byte |
| Full load | `curl %{time_total}` with `size_download >= 500000` (GitHub homepage ~525 KB) |
| Failure detection | Time for the hot path to detect the current hosts IP is down; TCP connect times out at 400 ms |
| Switch transaction | Decision → single-line hosts rewrite → verification → DNS cache flush, wall clock |
| End-to-end recovery | Failure detection + switch transaction, i.e. link failure to a usable new IP |
| Full cycle | Time for `discover()` to probe all 9 domains |

**Targets**: failure detection < 500 ms, switch transaction < 50 ms, **end-to-end recovery < 500 ms** (the three locally controllable metrics, consistently met); TTFB P95 < 1.2 s, full load P95 < 3.5 s (allowing for cross-border jitter).

**Before / after** (measured 2026-11-09):

| Metric | Before | After |
|---|---|---|
| End-to-end recovery | ~6 min (2 min poll × 2 failures + 3 min cooldown + 96 s full probe) | **~426 ms** (400 ms detection + 26.2 ms switch; log: `hotpath switch ... 26.2ms`) |
| Browser during failure | `ERR_CONNECTION_TIMED_OUT`, 8–20 s timeouts | Sub-second automatic switch |
| Full cycle | 96 s (9 domains serial) | **31 s** (domain-level concurrency; deterministic baseline 2721 → 612 ms, 4.45×) |
| Switch transaction | Full rebuild + `ipconfig /flushdns` subprocess | **26.2 ms** (single-line delta + Win32 DNS flush 7.12 ms) |
| TTFB / full load | 0.43–0.50 s / 1.07 s in a good window; no response during failure | 0.366–1.064 s / 1.019–3.029 s (**8/8** samples fully loaded, median 0.418 s / 1.465 s) |

**Architecture**: a resident "hot path" thread inside the supervisor is decoupled from the slow full probe. Every 3 s it concurrently micro-probes the built-in candidate pool and maintains `ip_pool.json` (RTT + failure counts); every 500 ms it checks the current `github.com` record and, on a failed connect probe, verifies ranked standby candidates live; only an IP that passes verification right now triggers a single-line hosts rewrite and the Win32 DNS flush API. If every candidate fails, it treats the outage as a network-layer block, leaves `hosts` untouched, and backs off instead of cycling through dead IPs. The full `discover()` is demoted to pool maintenance and still handles the other 8 domains plus 500 KB full-page body validation. While a worker cycle runs, the hot path pauses hosts writes (`CYCLE_RUNNING`) to avoid concurrent writes. When every candidate IP is unreachable it backs off to 2 s and throttles logging, avoiding a connection storm. A 400 ms connect probe can misclassify an intermittently slow but usable IP; a 5 s post-switch observation window plus a 10 s exclusion of the just-abandoned IP dampen flapping — measured browser access stayed 8/8 fully loaded in that window, so switching does not disrupt in-flight page loads.

**Trade-offs and scope**:

- Cross-border TCP/TLS handshake alone costs 250–450 ms, and transferring 525 KB adds 0.7–1.5 s. **TTFB and full load cannot reach single- or double-digit milliseconds**; the "millisecond" target applies to the **locally controllable detection and switch** (minutes → a few hundred ms). Beating the network floor would require domestic acceleration or a compliant proxy, changing the project's "no VPN" premise; not introduced here.
- When all candidate IPs are blocked at the network layer simultaneously (observed during testing), no hosts-based approach can recover; the hot path backs off and waits. This is a physical boundary, not a defect.
- Added: `ip_pool.json` runtime state, the `--hotpath-once` command, and `hotpath_*` config keys. All other CLIs, logs, `state.json` / `heartbeat.json`, the managed hosts block, backup/rollback, the desktop tool, and the no-auto-open-browser behavior are unchanged.
- Sustained probing generates roughly 1–3 HTTPS requests/second; set `hotpath_enabled: false` to revert to the original timer-based architecture.

### Code Map

The main program is a single file using only the Python standard library. Its existing functions fall into five groups, useful for locating code and reviewing changes:

| Group | Representative functions |
|---|---|
| IP discovery and probing | `doh_query`, `public_ipv4`, `probe`, `discover` |
| `hosts` transaction and safety | `decode_hosts`, `rebuild_hosts`, `backup_hosts`, `write_hosts_bytes`, `rollback`, `apply_hosts`, `flush_dns` |
| Self-healing and state | `run_cycle`, `verify`, `access_check`, `run_watchdog`, `run_daemon`, `write_heartbeat`, `pid_alive` |
| CLI and installation | `install_task`, `uninstall_task`, `show_status`, `do_rollback`, `open_github_page`, `main` |
| Hot path and failover | `micro_probe`, `refresh_pool`, `verify_and_switch`, `switch_domain_ip`, `hotpath_loop`, `_discover_one` |

Self-check entry points (no extra dependencies): `--help` lists every command; `--dry-run` probes without writing; `--status` is read-only; `--rollback` restores the most recent `hosts` backup.

### Prerequisites (summary)

Windows 10 / 11; Python 3.x (**no third-party packages**); one UAC approval on first run for administrator privileges; no Edge required (the program no longer launches a browser; the manual entry uses your default browser); at least one interactive logon session; DoH endpoints and GitHub IPs must be reachable. Full list: [`docs/PREREQUISITES.md`](docs/PREREQUISITES.md).

### Configuration (summary)

All behavior lives in `config.json` and is hot-reloaded each cycle, so changes need no restart. Adjustable: refresh interval range, timeouts and retries, monitored domains, DoH endpoints, protection thresholds, verification, and watchdog parameters. Every key has a built-in default, so the config file may be omitted entirely. Full table: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md); copyable template: `config.example.json`.

### Quick Start

1. Confirm Python 3 is installed and place this directory at a stable local path.
2. Double-click `run-as-admin.bat` and click "Yes" in the UAC prompt.
3. Inspect status:

```bat
py -3 github_hosts_keeper.py --status
```

The script registers the scheduled tasks and hands over to the daemon — **no console window needs to stay open afterwards**. IP discovery, `hosts` writing, and DNS flushing are handled by the program. Standard library only; no packages to install.

### Verification

```bat
py -3 github_hosts_keeper.py --dry-run
py -3 github_hosts_keeper.py --status
```

`--dry-run` only probes and writes nothing, useful for a pre-install check; in `--status`, "supervisor 健康: 是" (supervisor healthy: yes) together with `result: success` means it is currently working; `--rollback` restores the most recent `hosts` backup. Every command is listed by `py -3 github_hosts_keeper.py --help`.

Before reporting an issue or submitting a change, run the built-in self-checks; no test framework or third-party packages are needed:

| Command | Pass criterion |
|---|---|
| `py -3 github_hosts_keeper.py --help` | all 11 commands listed, no errors |
| `py -3 github_hosts_keeper.py --dry-run` | probes only, `hosts` untouched, exit code 0 |
| `py -3 github_hosts_keeper.py --status` | `result: success`, supervisor healthy |
| `py -3 -m py_compile github_hosts_keeper.py` | no syntax errors |
| `py -3 github_hosts_keeper.py --rollback` | restores the latest `hosts` backup when needed |

After editing configuration, keep the `config.json` and `config.example.json` key sets identical; after editing docs, keep both language sections in sync.

### Troubleshooting

| Symptom | What to do |
|---|---|
| UAC prompt on first run | Click "Yes". It registers the scheduled tasks and allows writing `hosts`; background runs do not prompt again. |
| A blue privilege window or console flashes briefly | The current version hides all spawned process windows. If it still appears, confirm you are running the current files in this directory and run `run-as-admin.bat` once more. |
| GitHub suddenly unreachable again | Run `py -3 github_hosts_keeper.py --once` to trigger a full rediscovery immediately; access-health checks also trigger one after consecutive failures. |
| "Heartbeat expired" followed by automatic recovery | Expected catch-up after sleep/wake. No action needed. |
| `config.json` changes seem ignored | Config is hot-reloaded every cycle and needs no restart; run `--once` to apply it immediately. |
| Want to open the GitHub page manually | Double-click `open-github.bat`, or run `py -3 github_hosts_keeper.py --open`. No background flow opens a page automatically. |
| Want to undo the `hosts` change | Run `py -3 github_hosts_keeper.py --rollback`. |
| `hosts` changed but the browser still fails | See "Notes" below: browser DoH, system proxies, and IPv6 preference can all bypass `hosts`. |

Please open an Issue with your `--status` output and the relevant lines from `github_hosts_keeper.log`; before submitting a change, follow the self-checks in [`CONTRIBUTING.md`](CONTRIBUTING.md).

### Notes

- **Limits**: only DNS-resolution issues are addressed. Full TLS/SNI interference, or total loss of both DoH and the candidate pool, cannot be fixed by `hosts`; the program preserves the existing configuration and reports a clear diagnosis.
- **Network setup**: browser "Secure DNS / DoH", system or browser proxies, VPNs, IPv6 preference, and gateway-enforced DNS hijacking can bypass `hosts`. Campus and corporate networks vary widely — verify on the target machine.
- **Runtime conditions**: does not run while powered off or without an interactive logon session; paused during sleep and caught up after wake (a "heartbeat expired" message followed by automatic recovery is expected). Restart cap is 3 per hour; exceeding it only raises an alert.
- **Coverage**: all 9 GitHub domains in the configuration, including `objects.githubusercontent.com` and `release-assets.githubusercontent.com` for direct release-asset / avatar downloads (these two use the built-in Fastly candidate pool instead of DoH); excludes SSH (`git@github.com:22`) and IPv6. GitHub login state, 2FA, organization SSO, and private-repo authorization are unrelated to this tool.
- **Security**: the scheduled task runs the script in this directory with highest privileges — keep the directory ACLs controlled so a tampered script cannot be used for privilege escalation. Only IPs from built-in sources, each individually validated, are used; do not mix in untrusted "hosts one-click packs".
- **Compliance**: intended solely to improve access to legitimate sites such as GitHub. Observe your organization's network policies and applicable laws and regulations.

---

> 中文与 English 两部分结构、条目与事实保持一致；如有差异，以程序源码与 `docs/` 为准。
> The Chinese and English sections share the same structure, items, and facts; in case of discrepancy, the source code and `docs/` are authoritative.

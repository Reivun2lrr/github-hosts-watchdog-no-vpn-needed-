# GitHub Hosts Watchdog

> 无需代理即可改善 GitHub 访问 · No VPN needed for everyday GitHub access

[中文](#中文) | [English](#english)

---

<a id="中文"></a>
## 中文

一次改 `hosts` 只能管用几天，IP 一失效又打不开 GitHub。**GitHub Hosts Watchdog** 是一套面向 Windows 的自动化访问自愈系统：定时从多个 DoH 源发现可用 IP，经 TLS 证书校验与 HTTPS 探测确认后安全写入 `hosts`，再由双层看门狗与访问健康巡检，让进程崩溃、系统睡眠唤醒、IP 在成功轮次之间失效等情况都能自动恢复。一次部署，长期免维护。

> 范围说明：本工具解决 **DNS 解析层面**的访问问题。若网络对全部 GitHub IP 实施 TLS/SNI 层干扰，`hosts` 方案无法恢复网页访问，程序会明确诊断而不是伪装成功。详见「注意事项」。

### 核心功能

- **可信 IP 发现**：3 个 DoH 端点（阿里 / Cloudflare / 腾讯）＋ 内置候选池；每域名最多 14 个候选、12 并发。每个候选须通过 TCP 443 连接、TLS 证书校验（SNI）与 HTTPS 请求，并拒绝私有／保留地址，防止 `hosts` 投毒。
- **安全写入事务**：仅替换受管理标记区块内的 GitHub 条目，自动清理重复与失效条目，其余 `hosts` 内容逐行原样保留；写前备份（保留 10 份）、写后字节校验、异常时字节级回滚，保留原文件编码、换行符与 ACL。有效记录少于阈值时完全不改动并提示。
- **生效与验证**：刷新 DNS 缓存 → 核对系统解析结果 → HTTPS 访问验证。全程不启动浏览器、不显示网页；网页仅在你主动执行 `--open` 或双击 `open-github.bat` 时打开，显示时机完全由你控制。
- **手动入口**：`open-github.bat`（双击）或 `py -3 github_hosts_keeper.py --open`，用默认浏览器打开 `https://github.com`。后台任务、自启、看门狗一律不调用它。
- **双层看门狗**：内部 supervisor 以独立子进程执行每轮任务（单轮超时强杀、异常计数）；外部计划任务每 5 分钟巡检心跳，对失联、僵尸进程、旧版本自动清理并拉起，含每小时重启上限。
- **访问健康巡检**：supervisor 空闲时轻量探测 `github.com`，连续失败达阈值即触发一轮完整 IP 重探测，补上「成功轮次之间 IP 失效」的发现空窗。
- **无人值守运行**：随机抖动间隔刷新（45–120 分钟）、失败后缩短至 10 分钟、登录自启（最高权限、取消 72 小时上限、支持电池与补跑）、单实例互斥、日志轮转与状态记录。
- **命令行接口**：11 个命令（含手动入口 `--open`），退出码 0–5 区分成功、无可用记录、权限不足、写入失败、验证失败与配置错误。详见程序 `--help`。

### 目录结构

| 文件 | 说明 |
|---|---|
| `github_hosts_keeper.py` | 主程序（单文件，约 1200 行，仅 Python 标准库） |
| `config.json` | 随附的默认配置，可直接使用或按需修改 |
| `config.example.json` | 与默认配置一致的对照模板，用于改坏后恢复默认值 |
| `run-as-admin.bat` | 一键启动器：申请 UAC → 注册两个计划任务 → 交由无窗口守护进程接管 |
| `open-github.bat` | **唯一手动入口**：双击才用默认浏览器打开 GitHub；任何后台流程都不会调用它 |
| `README.md` | 本文件（中英双语） |
| `docs/PREREQUISITES.md` | 使用前提（系统、权限、网络、会话） |
| `docs/CONFIGURATION.md` | 配置要求：全部配置项、默认值与调优建议 |
| `LICENSE` | MIT 许可证 |
| `.gitignore` | 排除运行时产物与本机数据 |

运行时产物 `state.json`、`heartbeat.json`、`github_hosts_keeper.log`、`backups/` 由程序自动生成，不纳入版本控制。

### 使用前提（摘要）

Windows 10 / 11；Python 3.x（**无需第三方库**）；首次运行需批准一次 UAC 以取得管理员权限；无需 Edge（程序不再启动浏览器，手动入口使用系统默认浏览器）；需要至少一个交互式登录会话；DoH 端点与 GitHub IP 需可达。完整清单见 [`docs/PREREQUISITES.md`](docs/PREREQUISITES.md)。

### 配置要求（摘要）

全部行为集中于 `config.json`，守护进程每轮热加载，改后无需重启。可调整刷新间隔范围、各类超时与重试、监控域名、DoH 端点、保护阈值、验证方式与看门狗参数；每项均有内置默认值，配置文件可整体省略。完整表格见 [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)，可复制模板见 `config.example.json`。

### 快速开始

1. 确认已安装 Python 3，将本目录放到一个稳定的本地路径。
2. 双击 `run-as-admin.bat`，在 UAC 弹窗点击「是」。脚本自动注册计划任务并完成守护交接，**之后无需保留任何控制台窗口**。
3. 执行 `py -3 github_hosts_keeper.py --status` 查看运行状态；程序会自动完成 IP 探测、`hosts` 写入与 DNS 刷新。

### 验证

`--status` 中「supervisor 健康: 是」且 `result: success` 表示当前可用；`--dry-run` 只探测不写任何文件，可用于安装前自检；`--rollback` 可还原最近一次 `hosts` 备份。

### 注意事项

- **能力边界**：只能解决 DNS 解析层面问题。TLS/SNI 层全量干扰、`DoH` 与候选池全部不可达时，`hosts` 无解，程序会保留原配置并明确诊断。
- **网络配置**：浏览器「安全 DNS / DoH」、系统或浏览器代理、VPN、IPv6 优先、网关强制 DNS 劫持都可能绕过 `hosts`；校园网与企业网策略差异较大，以本机验证为准。
- **运行条件**：关机或无交互式登录会话时不运行；睡眠期间暂停，唤醒后靠任务补跑（会看到「心跳过期」后自动恢复，属预期）。每小时重启上限为 3 次，超限只告警。
- **覆盖范围**：仅配置中的 7 个 GitHub 域名；不含 SSH（`git@github.com:22`）、IPv6、`objects.githubusercontent.com`（头像 / Release 附件）。GitHub 登录态、2FA、组织 SSO 与私有仓库授权与本工具无关。
- **安全**：计划任务以最高权限运行本目录下的脚本，请确保脚本目录权限受控，防止被篡改后借道提权。仅使用程序内置来源并逐个验证的 IP，请勿混用来源不明的「hosts 一键包」。
- **合规**：仅用于改善对 GitHub 等合法站点的访问体验，请遵守所在单位的网络使用规定与相关法律法规。

---

<a id="english"></a>
## English

Editing `hosts` once only works for a few days — GitHub becomes unreachable again as soon as the IP changes. **GitHub Hosts Watchdog** is a self-healing access system for Windows: it periodically discovers usable IPs from multiple DoH sources, validates them with TLS certificate checks and HTTPS probes, safely writes them to `hosts`, and relies on a two-layer watchdog plus access-health checks to recover automatically from process crashes, sleep/wake cycles, and IPs that expire between successful refresh cycles. Deploy once, maintain nothing.

> Scope: this tool solves access problems at the **DNS resolution** layer. If a network applies TLS/SNI-level interference to every GitHub IP, editing `hosts` cannot restore web access; the program reports this explicitly instead of pretending to succeed. See "Notes".

### Key Features

- **Trusted IP discovery**: 3 DoH endpoints (Alibaba / Cloudflare / Tencent) plus a built-in candidate pool; up to 14 candidates per domain, 12 concurrent probes. Each candidate must pass a TCP 443 connection, TLS certificate validation (SNI), and an HTTPS request; private/reserved addresses are rejected to prevent `hosts` poisoning.
- **Safe write transaction**: only the GitHub entries inside a managed marker block are replaced; duplicate and stale entries are cleaned while every other line of `hosts` is preserved verbatim. Backup before writing (10 retained), byte verification after writing, byte-level rollback on failure, with original encoding, line endings, and ACL preserved. If valid records fall below the threshold, `hosts` is left untouched with an explicit notice.
- **Activation and verification**: flush the DNS cache → confirm the system resolution → verify over HTTPS. No browser is launched and no page is displayed at any point.
- **Manual entry**: double-click `open-github.bat`, or run `py -3 github_hosts_keeper.py --open`, to open `https://github.com` in your default browser. No background task, autostart, or watchdog ever calls it — you control exactly when the page appears.
- **Two-layer watchdog**: an internal supervisor runs each cycle in a separate child process (hard timeout kill, failure counting); an external scheduled task checks the heartbeat every 5 minutes and cleans up / restarts lost, zombie, or legacy instances, with an hourly restart cap.
- **Access-health checks**: while the supervisor is idle it performs a lightweight `github.com` probe; consecutive failures trigger a full IP rediscovery cycle, closing the detection gap when an IP expires between successful cycles.
- **Unattended operation**: randomized jittered refresh (45–120 minutes), shortened to 10 minutes after failure, logon auto-start (highest privileges, no 72-hour limit, battery- and catch-up-friendly), single-instance mutex, log rotation, and state recording.
- **CLI**: 11 commands (including the manual `--open` entry); exit codes 0–5 distinguish success, no usable record, insufficient privileges, write failure, verification failure, and configuration error. See the program's `--help`.

### Project Structure

| File | Description |
|---|---|
| `github_hosts_keeper.py` | Main program (single file, ~1200 lines, standard library only) |
| `config.json` | Shipped default configuration, usable as-is or editable |
| `config.example.json` | Reference template identical to the defaults, for restoring them |
| `run-as-admin.bat` | One-click launcher: UAC → register both scheduled tasks → hand over to the windowless daemon |
| `README.md` | This file (bilingual: Chinese / English) |
| `docs/PREREQUISITES.md` | Prerequisites (system, privileges, network, session) |
| `docs/CONFIGURATION.md` | Configuration reference: every key, default, and tuning advice |
| `LICENSE` | MIT License |
| `.gitignore` | Excludes runtime artifacts and local data |

Runtime artifacts `state.json`, `heartbeat.json`, `github_hosts_keeper.log`, and `backups/` are generated automatically and are not version-controlled.

### Prerequisites (summary)

Windows 10 / 11; Python 3.x (**no third-party packages**); one UAC approval on first run for administrator privileges; no Edge required (the program no longer launches a browser; the manual entry uses your default browser); at least one interactive logon session; DoH endpoints and GitHub IPs must be reachable. Full list: [`docs/PREREQUISITES.md`](docs/PREREQUISITES.md).

### Configuration (summary)

All behavior lives in `config.json` and is hot-reloaded each cycle, so changes need no restart. Adjustable: refresh interval range, timeouts and retries, monitored domains, DoH endpoints, protection thresholds, verification, and watchdog parameters. Every key has a built-in default, so the config file may be omitted entirely. Full table: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md); copyable template: `config.example.json`.

### Quick Start

1. Confirm Python 3 is installed and place this directory at a stable local path.
2. Double-click `run-as-admin.bat` and click "Yes" in the UAC prompt. The script registers the scheduled tasks and hands over to the daemon — **no console window needs to stay open afterwards**.
3. Run `py -3 github_hosts_keeper.py --status` to inspect status; the program handles IP discovery, `hosts` writing, and DNS flushing automatically.

### Verification

In `--status`, "supervisor 健康: 是" (supervisor healthy: yes) together with `result: success` means it is currently working. `--dry-run` only probes and writes nothing, useful for a pre-install check; `--rollback` restores the most recent `hosts` backup.

### Notes

- **Limits**: only DNS-resolution issues are addressed. Full TLS/SNI interference, or total loss of both DoH and the candidate pool, cannot be fixed by `hosts`; the program preserves the existing configuration and reports a clear diagnosis.
- **Network setup**: browser "Secure DNS / DoH", system or browser proxies, VPNs, IPv6 preference, and gateway-enforced DNS hijacking can bypass `hosts`. Campus and corporate networks vary widely — verify on the target machine.
- **Runtime conditions**: does not run while powered off or without an interactive logon session; paused during sleep and caught up after wake (a "heartbeat expired" message followed by automatic recovery is expected). Restart cap is 3 per hour; exceeding it only raises an alert.
- **Coverage**: only the 7 GitHub domains in the configuration; excludes SSH (`git@github.com:22`), IPv6, and `objects.githubusercontent.com` (avatars / release assets). GitHub login state, 2FA, organization SSO, and private-repo authorization are unrelated to this tool.
- **Security**: the scheduled task runs the script in this directory with highest privileges — keep the directory ACLs controlled so a tampered script cannot be used for privilege escalation. Only IPs from built-in sources, each individually validated, are used; do not mix in untrusted "hosts one-click packs".
- **Compliance**: intended solely to improve access to legitimate sites such as GitHub. Observe your organization's network policies and applicable laws and regulations.

---

> 中文与 English 两部分结构、条目与事实保持一致；如有差异，以程序源码与 `docs/` 为准。
> The Chinese and English sections share the same structure, items, and facts; in case of discrepancy, the source code and `docs/` are authoritative.

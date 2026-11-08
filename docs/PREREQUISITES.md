# 使用前提 / Prerequisites

[中文](#中文) | [English](#english)

---

<a id="中文"></a>
## 中文

本页列出运行 GitHub Hosts Watchdog 前必须满足的条件。缺少任一项，程序可能以退出码 1–5 结束，或显示 `verify_failed`，但不会破坏现有 `hosts`。

| 类别 | 要求 | 不满足时的表现 |
|---|---|---|
| 操作系统 | Windows 10 / 11（依赖任务计划程序） | 无法注册自启任务；`--daemon` 仍可前台运行 |
| `hosts` 路径 | `C:\Windows\System32\drivers\etc\hosts` 可写 | 退出码 2 / 3；日志出现「拒绝访问」 |
| 运行时 | Python 3.x，**仅标准库，无需 pip 安装任何包** | 命令无法启动；启动器会依次尝试 `py -3` 与 `python` |
| 权限 | 首次运行需批准一次 UAC，账号须属于 Administrators 组 | 无法写入 `hosts`、无法注册「最高权限」任务 |
| 启动器 | `run-as-admin.bat`（自带提权，勿再右键「以管理员身份运行」） | 重复提权会造成无意义的二次弹窗 |
| 登录会话 | 至少一个**交互式登录会话**（`LogonType=Interactive`）；锁屏可以，注销后不登录 / 关机不运行 | 任务不触发；看门狗周期任务也无法补跑 |
| 计划任务 | 任务计划程序服务可用、两个任务未被禁用或删除 | 无心跳、无自动刷新 |
| 浏览器 | 后台流程完全不需要浏览器；手动打开网页时使用系统默认浏览器（`--open` / `open-github.bat`） | 无影响：验证一律走 HTTPS 直连 |
| 网络 | 3 个 DoH 端点至少一个可达；候选 GitHub IP 至少部分可达 | 退出码 1「无可用记录」，按设计保留原配置 |
| 系统时间 | 系统时钟正确（心跳基于 `time.time()`） | 时间跳变会误判心跳过期并触发无谓恢复 |
| 网络配置 | 避免浏览器「安全 DNS / DoH」、强制代理、VPN 虚拟网卡、IPv6 优先、网关强制 DNS 劫持绕过 `hosts` | `hosts` 写入成功但访问仍失败 |
| 目录权限 | 项目目录稳定且 ACL 受控（高权限任务会执行其中的脚本） | 路径变化导致任务静默失败；目录可写则存在提权面 |
| 电源 | 睡眠期间暂停，唤醒后靠 `StartWhenAvailable` 补跑 | 唤醒后可见「心跳过期」再自动恢复，属预期 |

### 只读操作无需管理员权限

`--status`（查看状态）与 `--dry-run`（仅探测、不写任何文件）可在普通权限命令提示符中运行。写入类操作（`--once`、`--install-task`、`--rollback`）以及 `hosts` 修改、计划任务注册均需管理员权限。

### 已知无法覆盖的场景

- 网络对全部 GitHub IP 实施 TLS/SNI 层干扰时，`hosts` 方案物理上无法恢复网页访问，需换网络或使用合规代理。
- 覆盖范围仅配置中的 7 个域名；SSH、IPv6、头像 / Release 附件域名未纳入。
- GitHub 账号登录态、cookie、2FA、组织 SSO、私有仓库授权与本工具无关。

完整配置说明见 [`CONFIGURATION.md`](CONFIGURATION.md)，项目说明见 [`../README.md`](../README.md)。

---

<a id="english"></a>
## English

This page lists the conditions required before running GitHub Hosts Watchdog. If any is missing, the program may exit with code 1–5 or report `verify_failed`, but it will not damage the existing `hosts`.

| Category | Requirement | Symptom when unmet |
|---|---|---|
| Operating system | Windows 10 / 11 (depends on Task Scheduler) | Auto-start tasks cannot be registered; `--daemon` can still run in the foreground |
| `hosts` path | `C:\Windows\System32\drivers\etc\hosts` must be writable | Exit code 2 / 3; "access denied" in the log |
| Runtime | Python 3.x, **standard library only, no pip packages** | Command fails to start; the launcher tries `py -3` then `python` |
| Privileges | One UAC approval on first run; account must be in Administrators | Cannot write `hosts` or register "Highest" tasks |
| Launcher | `run-as-admin.bat` (self-elevating; do not also right-click "Run as administrator") | Duplicate elevation causes a redundant prompt |
| Logon session | At least one **interactive logon session** (`LogonType=Interactive`); locking is fine, logged-off or powered-off states do not run | Tasks never trigger; the periodic watchdog cannot catch up either |
| Task Scheduler | Service available; both tasks enabled and present | No heartbeat, no automatic refresh |
| Browser | No browser is needed by any background flow; the manual entry (`--open` / `open-github.bat`) uses your default browser | No impact: verification is always plain HTTPS |
| Network | At least one of the 3 DoH endpoints reachable; at least some candidate GitHub IPs reachable | Exit code 1 "no usable records" — existing config preserved by design |
| System clock | Correct system time (heartbeat uses `time.time()`) | Clock jumps are misread as an expired heartbeat and trigger needless recovery |
| Network setup | Avoid browser "Secure DNS / DoH", forced proxies, VPN virtual adapters, IPv6 preference, or gateway DNS hijacking that bypass `hosts` | `hosts` is written successfully but access still fails |
| Directory ACL | Stable project path with controlled ACLs (the elevated task executes the script inside it) | Path changes make tasks fail silently; a writable directory creates a privilege-escalation surface |
| Power | Paused during sleep, caught up after wake via `StartWhenAvailable` | "Heartbeat expired" followed by automatic recovery after wake is expected |

### Read-only operations need no administrator privileges

`--status` (show status) and `--dry-run` (probe only, writes nothing) run in a normal command prompt. Write operations (`--once`, `--install-task`, `--rollback`), `hosts` modification, and task registration require administrator privileges.

### Known out-of-scope scenarios

- When a network applies TLS/SNI-level interference to every GitHub IP, editing `hosts` physically cannot restore web access; change networks or use a compliant proxy.
- Coverage is limited to the 7 domains in the configuration; SSH, IPv6, and avatar / release-asset domains are excluded.
- GitHub login state, cookies, 2FA, organization SSO, and private-repository authorization are unrelated to this tool.

See [`CONFIGURATION.md`](CONFIGURATION.md) for the full configuration reference and [`../README.md`](../README.md) for the project overview.

---

> 中文与 English 两部分条目与事实保持一致 / The Chinese and English sections share the same items and facts.

# 配置要求 / Configuration Reference

[中文](#中文) | [English](#english)

---

<a id="中文"></a>
## 中文

全部行为由项目根目录的 `config.json` 控制。守护进程**每轮热加载**，修改后立即生效，无需重启、无需重新注册计划任务。每个配置项都有内置默认值，因此配置文件可整体省略；`config.example.json` 是随附默认值的对照副本，可用于改坏后恢复。配置错误会被拦截并沿用上一份有效配置（退出码 5）。

下表「说明」列同时给出中文与英文，两个语言部分引用**同一张表**，因此信息天然一致。表中默认值与 `config.json` 完全一致。

### 配置表 / Configuration Table

| 分组 / Group | 配置键 / Key | 默认值 / Default | 说明 / Description |
|---|---|---|---|
| 间隔 / Interval | `interval_min_minutes` | `45` | 成功轮次后的最短刷新间隔（分钟） / Minimum refresh interval after a successful cycle (min) |
| 间隔 / Interval | `interval_max_minutes` | `120` | 成功轮次后的最长刷新间隔（分钟） / Maximum refresh interval after a successful cycle (min) |
| 间隔 / Interval | `failure_retry_minutes` | `10` | 失败后缩短到的重试间隔（分钟） / Retry interval after a failed cycle (min) |
| 间隔 / Interval | `jitter_ratio` | `0.2` | 随机抖动比例（±20%） / Random jitter ratio (±20%) |
| 超时 / Timeouts | `dns_timeout_seconds` | `6` | 单个 DoH 查询超时（秒） / Per-DoH query timeout (s) |
| 超时 / Timeouts | `connect_timeout_seconds` | `4` | 候选 IP 的 TCP 443 连接超时（秒） / TCP 443 connect timeout per candidate (s) |
| 超时 / Timeouts | `http_timeout_seconds` | `8` | HTTPS 探测与访问验证超时（秒） / HTTPS probe and verification timeout (s) |
| 超时 / Timeouts | `edge_verify_timeout_seconds` | `45` | 保留兼容键，当前不再启动浏览器 / Legacy key retained for compatibility; no browser is launched |
| 超时 / Timeouts | `flushdns_timeout_seconds` | `15` | `ipconfig /flushdns` 超时（秒） / DNS flush command timeout (s) |
| 重试 / Retries | `max_retries` | `3` | 网络类操作最大重试次数 / Maximum retries for network operations |
| 重试 / Retries | `retry_backoff_seconds` | `2` | 线性退避基数（秒） / Linear backoff base (s) |
| 探测 / Discovery | `max_candidates_per_domain` | `14` | 每域名最多探测的候选 IP 数 / Max candidate IPs probed per domain |
| 探测 / Discovery | `probe_workers` | `12` | 并发探测线程数 / Concurrent probe workers |
| 探测 / Discovery | `domains` | 9 个域名 | 需要维护的 GitHub 域名列表 / GitHub domains to maintain: `github.com`, `api.github.com`, `codeload.github.com`, `raw.githubusercontent.com`, `gist.githubusercontent.com`, `gist.github.com`, `github.global.ssl.fastly.net`, `objects.githubusercontent.com`, `release-assets.githubusercontent.com`（后两项走内置 Fastly 候选池，不做 DoH 查询） |
| 探测 / Discovery | `doh_endpoints` | 3 个端点 | DoH 查询模板（含 `{domain}` 占位符） / DoH query templates with a `{domain}` placeholder: Alibaba, Cloudflare, Tencent |
| 热路径 / Hot Path | `hotpath_enabled` | `true` | 常驻亚秒级故障切换总开关；`false` 退回原定时架构 / Master switch; `false` reverts to the timer-based design |
| 热路径 / Hot Path | `hotpath_interval_ms` | `500` | 当前 IP 检测间隔（毫秒） / Current-IP check interval (ms) |
| 热路径 / Hot Path | `hotpath_probe_timeout_ms` / `hotpath_connect_timeout_ms` | `900` / `400` | 单次探测总超时 / TCP 快速判死超时（毫秒） / Total probe timeout / fast TCP connect timeout (ms) |
| 热路径 / Hot Path | `hotpath_fail_threshold` / `hotpath_switch_cooldown_ms` | `1` / `5000` | 触发切换的连续失败次数 / 切换后观察期（毫秒，抑制来回抖动） / Failures before switch / post-switch observation window (ms, dampens flapping) |
| 热路径 / Hot Path | `hotpath_pool_refresh_ms` / `hotpath_pool_size` / `hotpath_backoff_ms` | `3000` / `8` / `2000` | 池刷新间隔 / 池容量 / 全阻断退避（毫秒） / Pool refresh / size / all-blocked backoff (ms) |
| 热路径 / Hot Path | `hotpath_pool_path` | `ip_pool.json` | IP 池运行时状态文件，不纳入版本控制 / Runtime pool state file, not version-controlled |
| 保护 / Safety | `min_valid_records` | `2` | 有效记录少于该值则完全不改动 `hosts` / If fewer valid records exist, `hosts` is left untouched |
| 验证 / Verification | `verify_url` | `https://github.com` | 写入后的 HTTPS 验证地址，也是手动入口打开的地址 / URL for post-write HTTPS verification and for the manual open entry |
| 验证 / Verification | `open_edge` | `false` | 已停用：自动打开网页已移除，设为 `true` 也不会生效 / Deprecated: automatic page opening removed; `true` has no effect |
| 验证 / Verification | `headless_verify` | `false` | 已停用：自动无头浏览器验证已移除 / Deprecated: automatic headless browser check removed |
| 验证 / Verification | `edge_path` | `""` | 保留兼容键，当前不再使用 / Legacy key retained for compatibility; unused |
| 路径 / Paths | `backup_keep` | `10` | 保留的 `hosts` 备份份数 / Number of `hosts` backups retained |
| 路径 / Paths | `log_max_bytes` | `1048576` | 单个日志文件轮转阈值（字节） / Log rotation threshold in bytes |
| 路径 / Paths | `log_backup_count` | `3` | 保留的轮转日志份数 / Number of rotated logs retained |
| 路径 / Paths | `log_path` | `github_hosts_keeper.log` | 运行日志路径 / Runtime log path |
| 路径 / Paths | `state_path` | `state.json` | 状态文件路径 / State file path |
| 路径 / Paths | `backup_dir` | `backups` | 备份目录 / Backup directory |
| 任务 / Tasks | `task_name` | `GitHubHostsKeeper` | 主计划任务名称（登录触发） / Main scheduled task name (AtLogOn) |
| 任务 / Tasks | `python_executable` | `""` | 任务使用的 Python 可执行文件，空为自动探测 / Python executable for the tasks; empty means auto-detect |
| 看门狗 / Watchdog | `watchdog_enabled` | `true` | 是否注册并启用外部看门狗任务 / Whether to register and enable the external watchdog task |
| 看门狗 / Watchdog | `watchdog_task_name` | `GitHubHostsKeeper-Watchdog` | 看门狗计划任务名称 / Watchdog scheduled task name |
| 看门狗 / Watchdog | `watchdog_interval_minutes` | `5` | 外部巡检周期（分钟） / External health-check interval (min) |
| 看门狗 / Watchdog | `heartbeat_path` | `heartbeat.json` | 心跳文件路径 / Heartbeat file path |
| 看门狗 / Watchdog | `heartbeat_interval_seconds` | `30` | 心跳续期间隔（秒），长任务期间也续 / Heartbeat renewal interval (s), renewed even during long tasks |
| 看门狗 / Watchdog | `heartbeat_timeout_seconds` | `120` | 心跳判失联阈值（秒），须 ≥ 2× 续期间隔 / Heartbeat staleness threshold (s), must be ≥ 2× renewal interval |
| 看门狗 / Watchdog | `cycle_timeout_seconds` | `900` | 单轮 worker 硬超时，超时强杀（秒） / Hard timeout for one worker cycle, killed on expiry (s) |
| 看门狗 / Watchdog | `watchdog_max_restarts_per_hour` | `3` | 每小时最多重启次数，超限只告警 / Maximum restarts per hour; exceeding it only alerts |
| 看门狗 / Watchdog | `watchdog_verify_delay_seconds` | `20` | 恢复后复核心跳的等待时间（秒） / Delay before verifying the heartbeat after recovery (s) |
| 看门狗 / Watchdog | `watchdog_kill_stale_daemon` | `true` | 是否清理失联／旧版守护进程 / Whether to clean up stale or legacy daemons |
| 任务 / Tasks | `task_command_timeout_seconds` | `40` | PowerShell 任务命令超时（秒） / PowerShell task command timeout (s) |
| 访问巡检 / Access check | `health_check_enabled` | `true` | 是否启用看门狗侧访问巡检 / Whether to enable watchdog-side access checks |
| 访问巡检 / Access check | `health_check_timeout_seconds` | `8` | 单次访问巡检超时（秒） / Per-check timeout (s) |
| 访问巡检 / Access check | `health_fail_threshold` | `2` | 连续失败几次才触发立即刷新（去抖） / Consecutive failures before triggering an immediate refresh |
| 访问巡检 / Access check | `health_trigger_cooldown_minutes` | `15` | 触发后的冷却期（分钟），防反复重启 / Cooldown after a trigger (min), preventing restart loops |
| 元信息 / Meta | `_comment` | 字符串 | 配置文件内说明文字，程序忽略 / In-file note, ignored by the program |

### 调优建议

- 网络抖动大时，把 `health_fail_threshold` 调到 `3`、`health_trigger_cooldown_minutes` 调到 `20`，减少不必要的重探测。
- 想更快发现 IP 失效，可缩小 `interval_min_minutes` / `interval_max_minutes`；代价是更频繁的 DoH 查询与 HTTPS 探测。
- `heartbeat_timeout_seconds` 必须至少是 `heartbeat_interval_seconds` 的 2 倍，否则会误判失联；程序在加载配置时会校验并拒绝非法值。
- 网页**只由你主动打开**：后台流程（单轮、守护、看门狗、访问巡检、计划任务）一律不启动浏览器、不弹出网页。想打开时执行 `--open` 或双击 `open-github.bat`。`open_edge` / `headless_verify` / `edge_path` 仅为兼容保留，改动它们不会恢复自动打开。

### 生效与回滚

配置热加载失败时沿用上一份有效配置并写日志。`config.json` 缺失时使用内置默认值。任何 `hosts` 写入失败都会回滚到写前备份，备份位于 `backup_dir`。

项目说明见 [`../README.md`](../README.md)，运行前提见 [`PREREQUISITES.md`](PREREQUISITES.md)。

---

<a id="english"></a>
## English

All behavior is controlled by `config.json` in the project root. The daemon **hot-reloads it every cycle**, so changes take effect immediately — no restart and no task re-registration. Every key has a built-in default, so the config file may be omitted entirely; `config.example.json` is a reference copy of the shipped defaults for restoring them. Invalid configuration is rejected and the last valid configuration is retained (exit code 5).

The "Description" column of the table below is bilingual, and both language sections reference **the same table**, so the information is consistent by construction. All defaults match `config.json` exactly. See [Configuration Table](#配置表--configuration-table).

### Tuning advice

- On a jittery network, set `health_fail_threshold` to `3` and `health_trigger_cooldown_minutes` to `20` to reduce unnecessary rediscovery.
- To detect expired IPs sooner, lower `interval_min_minutes` / `interval_max_minutes`; the cost is more frequent DoH queries and HTTPS probes.
- `heartbeat_timeout_seconds` must be at least twice `heartbeat_interval_seconds`, otherwise the supervisor is falsely declared lost; the loader validates and rejects invalid values.
- Web pages open **only when you ask for them**: no background flow (single run, daemon, watchdog, health check, scheduled task) launches a browser or displays a page. Use `--open` or double-click `open-github.bat`. `open_edge`, `headless_verify` and `edge_path` are kept only for compatibility; changing them cannot re-enable automatic opening.

### Activation and rollback

If a hot reload fails, the previous valid configuration is kept and the failure is logged. If `config.json` is missing, built-in defaults are used. Any failed `hosts` write is rolled back to the pre-write backup stored in `backup_dir`.

See [`../README.md`](../README.md) for the project overview and [`PREREQUISITES.md`](PREREQUISITES.md) for prerequisites.

---

> 中文与 English 两部分共享同一张配置表与同一组默认值 / Both sections share one configuration table and one set of defaults.

# 贡献与反馈 / Contributing

这个项目的底线只有一条：**不引入第三方依赖，不改变对外行为**。下面的检查全部用程序自带的命令完成，不需要安装测试框架。

[中文](#中文) | [English](#english)

---

<a id="中文"></a>
## 中文

### 反馈问题

在 [Issues](https://github.com/Reivun2lrr/github-hosts-watchdog-no-vpn-needed-/issues) 开一条，附上：

1. `py -3 github_hosts_keeper.py --status` 的完整输出；
2. `github_hosts_keeper.log` 中相关时段的片段；
3. Windows 版本、`py -3 --version` 的结果、网络类型（校园网 / 家庭宽带 / 企业网络）。

上报前请自行打码本机用户名、内网地址等敏感信息；不要粘贴 `hosts` 文件内容以外的系统配置。使用类问题也可以在已开启的 [Discussions](https://github.com/Reivun2lrr/github-hosts-watchdog-no-vpn-needed-/discussions) 讨论。

### 提交改动前的自检

| 命令 | 通过标准 |
|---|---|
| `py -3 github_hosts_keeper.py --help` | 11 个命令全部列出，无异常 |
| `py -3 github_hosts_keeper.py --dry-run` | 只探测、不写 `hosts`，退出码 0 |
| `py -3 github_hosts_keeper.py --status` | `result: success`、`supervisor 健康: 是` |
| `py -3 -m py_compile github_hosts_keeper.py` | 无语法错误 |

另外：改了配置要确认 `config.json` 与 `config.example.json` 键集合一致；改了说明要同步 `README.md` 的中文与 English 两部分；新增运行时产物要加进 `.gitignore`。

### 边界

- 仅使用 Python 3 标准库，不新增运行时依赖、服务或后台组件。
- 不改变现有命令行参数、退出码、`state.json` / `heartbeat.json` 格式、`hosts` 受管理区块、备份与回滚行为。
- 不自动打开浏览器；网页只由 `--open` / `open-github.bat` 手动触发。
- 改动应能在国内网络、无代理环境下按 `README.md` 快速开始复现验证。
- 不承诺响应时间；反馈按维护者可用时间处理。

许可：MIT，见 [LICENSE](LICENSE)。

---

<a id="english"></a>
## English

### Reporting an issue

Open an [Issue](https://github.com/Reivun2lrr/github-hosts-watchdog-no-vpn-needed-/issues) with:

1. the full output of `py -3 github_hosts_keeper.py --status`;
2. the relevant lines from `github_hosts_keeper.log`;
3. your Windows version, `py -3 --version`, and network type (campus / home broadband / corporate).

Redact local usernames, private addresses, and anything else sensitive before posting. Usage questions also fit the enabled [Discussions](https://github.com/Reivun2lrr/github-hosts-watchdog-no-vpn-needed-/discussions).

### Before submitting a change

| Command | Pass criterion |
|---|---|
| `py -3 github_hosts_keeper.py --help` | all 11 commands listed, no errors |
| `py -3 github_hosts_keeper.py --dry-run` | probes only, `hosts` untouched, exit code 0 |
| `py -3 github_hosts_keeper.py --status` | `result: success`, supervisor healthy |
| `py -3 -m py_compile github_hosts_keeper.py` | no syntax errors |

Also: keep the `config.json` and `config.example.json` key sets identical, keep both README language sections in sync, and add any new runtime artifact to `.gitignore`.

### Boundaries

- Python 3 standard library only; no new runtime dependencies, services, or background components.
- Do not change existing CLI flags, exit codes, `state.json` / `heartbeat.json` formats, the managed `hosts` block, or backup/rollback behavior.
- No automatic browser opening; pages appear only via the manual `--open` / `open-github.bat` entry.
- Changes must be verifiable with the README quick start on a proxy-free network.
- Response times are not guaranteed; issues are handled as maintainer time allows.

Licensed under MIT; see [LICENSE](LICENSE).

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Hosts Keeper  --  Windows 自动化维护 GitHub hosts 解析

功能:
  1. 通过 DoH + 内置候选池发现 IP, 用「TLS 证书校验 + HTTPS 请求」双重验证可用性
  2. 仅替换受管理区块内的 GitHub 条目, 清理重复/失效条目, 其余 hosts 内容原样保留
  3. 写入前备份、写入后校验、异常自动回滚、管理员权限检查
  4. 无可用记录时不改动 hosts, 保留现有配置并提示
  5. 刷新 DNS 缓存, 以 HTTPS 直连验证页面可达性(不启动浏览器、不显示网页)
  6. 非固定(随机抖动)间隔守护运行, 记录日志与状态, 可注册登录自启任务
     —— 所有后台流程均不会打开任何网页; 打开网页只有唯一的手动入口 --open
  7. 双层看门狗: 内部 supervisor 监控 worker 子进程(超时强杀/异常重启),
     外部周期任务监控 supervisor 心跳(失联/僵尸/旧版本自动拉起)
  8. 访问健康巡检: 看门狗在 supervisor 空闲时轻量探测 github.com, 连续失败
     即触发一轮完整 IP 重探测, 补上成功轮次之间 IP 失效的发现空窗
  9. 所有后台外部命令(PowerShell / ipconfig / 派生 Python)均以无窗口模式执行,
     不出现控制台窗口闪现; 权限级别、提权流程与命令行为保持不变

  10. 热路径(Hot Path): supervisor 内常驻线程维护预热 IP 池, 500ms 级检测当前 IP,
      失效时亚秒级增量切换 hosts 并直接刷新 Win32 DNS 缓存; 慢速全量探测降为池维护

命令(原有接口全部保留):
  python github_hosts_keeper.py --hotpath-once  热路径单次检测/切换(新增, 不打开网页)
  python github_hosts_keeper.py --once              单次更新(默认)
  python github_hosts_keeper.py --daemon           守护运行(现为 supervisor)
  python github_hosts_keeper.py --install-task     注册自启 + 看门狗任务(需管理员)
  python github_hosts_keeper.py --daemon --install-task   注册并立即守护运行
  python github_hosts_keeper.py --uninstall-task  取消自启与看门狗任务
  python github_hosts_keeper.py --status          查看运行状态
  python github_hosts_keeper.py --dry-run         仅探测并打印计划, 不写任何文件
  python github_hosts_keeper.py --rollback        还原最近一次备份
  python github_hosts_keeper.py --watchdog        看门狗单次检查(供周期任务调用)
  python github_hosts_keeper.py --cycle           内部: 执行单轮更新(supervisor 调用)
  python github_hosts_keeper.py --open            【手动入口】在默认浏览器打开 GitHub
                                                  (也可双击 open-github.bat)

退出码: 0 成功 / 1 无可用记录(保留原配置) / 2 权限不足 / 3 写入或回滚失败
        / 4 hosts 已更新但页面仍不可达 / 5 配置错误
"""
from __future__ import annotations

import argparse
import ctypes
import ipaddress
import json
import logging
import os
import random
import re
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE = Path(__file__).resolve().parent
HOSTS = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
BEGIN = "# >>> GitHub Hosts Keeper BEGIN >>>"
END = "# <<< GitHub Hosts Keeper END <<<"
IPV4 = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+(\S+)")
IPV4_ONLY = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def hidden_process_kwargs() -> dict:
    """后台外部命令统一不分配/不显示控制台窗口, 消除蓝窗闪现.

    只改变窗口呈现方式: 命令行参数、权限级别、stdout/stderr 捕获、返回码与
    超时处理全部保持原样; 不新增任何进程、窗口或弹窗。
    """
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return {"creationflags": CREATE_NO_WINDOW, "startupinfo": si}


DEFAULTS = {
    "interval_min_minutes": 45,
    "interval_max_minutes": 120,
    "failure_retry_minutes": 10,
    "jitter_ratio": 0.2,
    "dns_timeout_seconds": 6,
    "connect_timeout_seconds": 4,
    "http_timeout_seconds": 8,
    "edge_verify_timeout_seconds": 45,
    "flushdns_timeout_seconds": 15,
    "max_retries": 3,
    "retry_backoff_seconds": 2,
    "max_candidates_per_domain": 14,
    "probe_workers": 12,
    "domains": [
        "github.com", "api.github.com", "codeload.github.com",
        "raw.githubusercontent.com", "gist.githubusercontent.com",
        "gist.github.com", "github.global.ssl.fastly.net",
    ],
    "doh_endpoints": [
        "https://dns.alidns.com/resolve?name={domain}&type=A",
        "https://cloudflare-dns.com/dns-query?name={domain}&type=A",
        "https://doh.pub/dns-query?name={domain}&type=A",
    ],
    "min_valid_records": 2,
    "verify_url": "https://github.com",
    # 仅保留配置键以兼容旧 config.json；自动流程一律不启动浏览器、不打开网页。
    # 打开网页只有唯一手动入口：--open / open-github.bat（见 open_github_page）。
    "open_edge": False,
    "headless_verify": False,
    "edge_path": "",
    "backup_keep": 10,
    "log_max_bytes": 1048576,
    "log_backup_count": 3,
    "log_path": "github_hosts_keeper.log",
    "state_path": "state.json",
    "backup_dir": "backups",
    "task_name": "GitHubHostsKeeper",
    "python_executable": "",

    # ---- 看门狗 ----
    "watchdog_enabled": True,
    "watchdog_task_name": "GitHubHostsKeeper-Watchdog",
    "watchdog_interval_minutes": 5,
    "heartbeat_path": "heartbeat.json",
    "heartbeat_interval_seconds": 30,
    "heartbeat_timeout_seconds": 120,
    "cycle_timeout_seconds": 900,
    "watchdog_max_restarts_per_hour": 3,
    "watchdog_verify_delay_seconds": 20,
    "watchdog_kill_stale_daemon": True,
    "task_command_timeout_seconds": 40,

    # ---- 访问健康巡检: 补上「成功轮次之间 IP 失效无人发现」的空窗 ----
    "health_check_enabled": True,
    "health_check_timeout_seconds": 8,
    "health_fail_threshold": 2,
    "health_trigger_cooldown_minutes": 15,

    # ---- 热路径: 常驻亚秒级故障切换(与慢速全量探测解耦) ----
    "hotpath_enabled": True,
    "hotpath_interval_ms": 500,
    "hotpath_probe_timeout_ms": 900,
    "hotpath_connect_timeout_ms": 400,
    "hotpath_backoff_ms": 2000,
    "hotpath_fail_threshold": 1,
    "hotpath_switch_cooldown_ms": 1500,
    "hotpath_pool_refresh_ms": 3000,
    "hotpath_pool_size": 8,
    "hotpath_pool_path": "ip_pool.json",
}

# 内置候选池: DoH 全失败时仍可工作; 每个候选都必须通过 TLS 证书校验才会被采用
SEEDS = {
    "github.com": ["20.27.177.113", "20.205.243.166", "140.82.112.3", "140.82.112.4",
                   "140.82.113.3", "140.82.113.4", "140.82.114.3", "140.82.114.4",
                   "140.82.116.4", "140.82.121.4", "20.200.245.247"],
    "gist.github.com": ["140.82.112.3", "140.82.114.4", "20.205.243.166"],
    "api.github.com": ["140.82.112.5", "140.82.112.6", "140.82.114.5", "140.82.114.6",
                       "20.205.243.168"],
    "codeload.github.com": ["140.82.112.9", "140.82.112.10", "140.82.113.9", "140.82.113.10",
                            "140.82.114.9", "140.82.114.10", "20.205.243.165"],
    "raw.githubusercontent.com": ["185.199.108.133", "185.199.109.133",
                                  "185.199.110.133", "185.199.111.133"],
    "gist.githubusercontent.com": ["185.199.108.133", "185.199.109.133",
                                   "185.199.110.133", "185.199.111.133"],
    "github.global.ssl.fastly.net": ["151.101.1.194", "151.101.65.194",
                                     "151.101.129.194", "151.101.193.194", "199.232.69.194"],
    "objects.githubusercontent.com": ["185.199.108.133", "185.199.109.133",
                                       "185.199.110.133", "185.199.111.133"],
    "release-assets.githubusercontent.com": ["185.199.108.133", "185.199.109.133",
                                              "185.199.110.133", "185.199.111.133"],
}

# Release 附件 CDN 走固定 Fastly 段: 实测 DoH 会返回超时 IP, 且这两项无需 DNS 解析。
# 直接探测内置候选池更快也更可靠(仍逐个做 TLS 证书校验 + 正文读取)。
SEED_ONLY_DOMAINS = {"objects.githubusercontent.com",
                     "release-assets.githubusercontent.com"}

# 探测/巡检必须真正收到响应正文才算可用。只读响应头会把「头通但正文传不下来」
# 的 IP 误判为最快(表现为浏览器打不开页面、curl 完整下载 0 字节超时)。
# github.com 首页约 525 KB; 只读取前 64 KB 仍会漏掉「传到 400 KB 后被重置」的 IP,
# 因此探测改为读完整页, 并优先采用能读满正文的 IP。
PROBE_BODY_LIMIT = 600000
FULL_PAGE_MIN_BYTES = 500000
# 访问巡检必须与探测口径一致: 只读 256 KB 会把「头通、正文卡住」的失效 IP 判为可用,
# 表现为 state.json=success 但浏览器打不开。改为读满整页并校验字节数。
CHECK_BODY_LIMIT = 600000

# 热路径微探测只要求响应头 + 至少 4 KB 正文; 整页 500 KB 校验仍由全量 discover 承担。
HOTPATH_MIN_BODY = 4096

log = logging.getLogger("ghk")
_stop = threading.Event()
CYCLE_RUNNING = threading.Event()   # supervisor 跑 worker 时, 热路径暂停写 hosts 避免并发写冲突


# ---------------------------------------------------------------- 基础设施

def setup_logging(cfg):
    log.setLevel(logging.INFO)
    for h in log.handlers:                          # 守护进程热加载时避免文件句柄泄漏
        try:
            h.close()
        except Exception:
            pass
    log.handlers.clear()
    p = resolve(cfg["log_path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(p, maxBytes=int(cfg["log_max_bytes"]),
                             backupCount=int(cfg["log_backup_count"]), encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(ch)
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass


def resolve(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else BASE / q


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    f = BASE / "config.json"
    if f.exists():
        try:
            cfg.update(json.loads(f.read_text(encoding="utf-8-sig")))
        except Exception as e:
            raise ValueError(f"config.json 解析失败: {e}")
    cfg.pop("_comment", None)
    if not (1 <= float(cfg["interval_min_minutes"]) <= float(cfg["interval_max_minutes"])):
        raise ValueError("需满足 1 <= interval_min_minutes <= interval_max_minutes")
    if int(cfg["max_retries"]) < 1 or int(cfg["probe_workers"]) < 1:
        raise ValueError("max_retries / probe_workers 必须 >= 1")
    for k in ("dns_timeout_seconds", "connect_timeout_seconds", "http_timeout_seconds",
              "edge_verify_timeout_seconds", "flushdns_timeout_seconds",
              "heartbeat_interval_seconds", "heartbeat_timeout_seconds",
              "cycle_timeout_seconds", "watchdog_verify_delay_seconds",
              "task_command_timeout_seconds"):
        if float(cfg[k]) <= 0:
            raise ValueError(f"{k} 必须 > 0")
    if float(cfg["watchdog_interval_minutes"]) < 1:
        raise ValueError("watchdog_interval_minutes 必须 >= 1")
    if int(cfg["watchdog_max_restarts_per_hour"]) < 1:
        raise ValueError("watchdog_max_restarts_per_hour 必须 >= 1")
    if float(cfg["health_check_timeout_seconds"]) <= 0:
        raise ValueError("health_check_timeout_seconds 必须 > 0")
    if int(cfg["health_fail_threshold"]) < 1:
        raise ValueError("health_fail_threshold 必须 >= 1")
    if float(cfg["health_trigger_cooldown_minutes"]) < 1:
        raise ValueError("health_trigger_cooldown_minutes 必须 >= 1")
    if float(cfg["heartbeat_timeout_seconds"]) < 2 * float(cfg["heartbeat_interval_seconds"]):
        raise ValueError("heartbeat_timeout_seconds 至少应为 heartbeat_interval_seconds 的 2 倍")
    if float(cfg["cycle_timeout_seconds"]) < float(cfg["heartbeat_interval_seconds"]):
        raise ValueError("cycle_timeout_seconds 不能小于 heartbeat_interval_seconds")
    if not cfg["domains"]:
        raise ValueError("domains 不能为空")
    return cfg


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_state(cfg) -> dict:
    f = resolve(cfg["state_path"])
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def update_state(cfg, patch: dict, history: bool = False):
    """原子替换写 state.json. 多进程并发时最后一次写入生效(不会损坏文件)."""
    f = resolve(cfg["state_path"])
    f.parent.mkdir(parents=True, exist_ok=True)
    st = load_state(cfg)
    st.update(patch)
    if history:
        entry = {k: st.get(k) for k in ("last_run", "result", "message", "verified_count")}
        hist = st.get("history", [])
        hist.insert(0, entry)
        st["history"] = hist[:20]
    tmp = f.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def save_state(cfg, patch: dict):
    """兼容原接口: 记录一条运行历史. 高频心跳/看门狗用 update_state."""
    update_state(cfg, patch, history=True)


def write_heartbeat(cfg, **extra):
    """独立心跳文件, 与 state.json 分离, 避免高频写入互相覆盖."""
    f = resolve(cfg["heartbeat_path"])
    f.parent.mkdir(parents=True, exist_ok=True)
    data = {"epoch": time.time(), "timestamp": now(),
            "pid": os.getpid(), "mode": "supervisor", **extra}
    tmp = f.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)
    return data


def read_heartbeat(cfg) -> dict | None:
    try:
        d = json.loads(resolve(cfg["heartbeat_path"]).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and d.get("epoch") else None
    except Exception:                                # noqa: BLE001
        return None


def pid_alive(pid) -> bool:
    """查询进程是否存活, 不依赖外部命令."""
    try:
        k = ctypes.windll.kernel32
        k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        k.OpenProcess.restype = ctypes.c_void_p
        k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        k.GetExitCodeProcess.restype = ctypes.c_int
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k.OpenProcess(0x1000, 0, int(pid))     # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_uint32()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259       # STILL_ACTIVE
    except Exception:                                # noqa: BLE001
        return False


def with_retries(fn, cfg, label):
    """统一重试: 异常时按 retry_backoff_seconds 线性退避, 返回 (结果, 错误)"""
    err = None
    for i in range(int(cfg["max_retries"])):
        try:
            return fn(), None
        except Exception as e:                       # noqa: BLE001 - 重试封装需捕获全部异常
            err = e
            log.warning("%s 第 %d/%d 次失败: %s", label, i + 1, cfg["max_retries"], e)
            if i + 1 < int(cfg["max_retries"]):
                time.sleep(float(cfg["retry_backoff_seconds"]) * (i + 1))
    return None, err


# ---------------------------------------------------------------- IP 发现与验证

def doh_query(domain: str, cfg) -> list[str]:
    found = []
    for tpl in cfg["doh_endpoints"]:
        url = tpl.format(domain=domain)
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "GitHubHostsKeeper/1.0",
                "accept": "application/dns-json",
            })
            with urllib.request.urlopen(req, timeout=float(cfg["dns_timeout_seconds"])) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            for a in data.get("Answer", []):
                ip = a.get("data", "")
                if IPV4_ONLY.match(ip) and a.get("type", 1) == 1:
                    found.append(ip)
        except Exception as e:                       # noqa: BLE001
            log.debug("DoH %s -> %s: %s", domain, url.split("/")[2], e)
    return found


def public_ipv4(ip: str) -> bool:
    try:
        return ipaddress.IPv4Address(ip).is_global
    except Exception:
        return False


def probe(domain: str, ip: str, cfg) -> dict | None:
    """TCP 443 + TLS 证书校验(SNI=domain) + GET 并读取响应正文.

    按「握手 + 响应头 + 正文」总耗时排序; 正文读取卡住(socket 超时)即淘汰,
    避免选中「响应头可达但内容传不下来」的 IP。证书校验可防止写入恶意 IP。
    """
    if not public_ipv4(ip):
        return None
    timeout = float(cfg["connect_timeout_seconds"])
    http_timeout = float(cfg["http_timeout_seconds"])
    t0 = time.time()
    try:
        ctx = ssl.create_default_context()          # check_hostname=True, CERT_REQUIRED
        with socket.create_connection((ip, 443), timeout=timeout) as raw:
            raw.settimeout(http_timeout)
            with ctx.wrap_socket(raw, server_hostname=domain) as s:
                req = (f"GET / HTTP/1.1\r\nHost: {domain}\r\n"
                       "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "GitHubHostsKeeper/1.0\r\n"
                       "Accept: */*\r\nConnection: close\r\n\r\n")
                s.sendall(req.encode("ascii"))
                buf = b""
                while b"\r\n\r\n" not in buf and len(buf) < 16384:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                m = re.search(rb"HTTP/[\d.]+ (\d{3})", buf)
                if not m or int(m.group(1)) >= 500:
                    return None
                body = buf.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in buf else b""
                got = len(body)
                while got < PROBE_BODY_LIMIT:
                    chunk = s.recv(min(8192, PROBE_BODY_LIMIT - got))
                    if not chunk:
                        break
                    got += len(chunk)
        latency = time.time() - t0
        if latency > http_timeout:
            return None
        return {"ip": ip, "status": int(m.group(1)),
                "latency": round(latency, 3), "body_bytes": got}
    except Exception:                               # noqa: BLE001 - 正文卡住/不可达即淘汰
        return None


def _discover_one(domain: str, cfg) -> tuple[str, str | None, dict]:
    """单域名探测; 供域名级并发调用。"""
    if domain in SEED_ONLY_DOMAINS:
        ips = []                       # 固定 CDN 段: 跳过被污染的 DoH 查询
    else:
        def query_or_raise(d=domain):
            r = doh_query(d, cfg)
            if not r:
                raise RuntimeError("所有 DoH 端点均无响应")
            return r
        ips, _ = with_retries(query_or_raise, cfg, f"DoH-{domain}")
    candidates = []
    for ip in (ips or []) + SEEDS.get(domain, []):
        if ip not in candidates and public_ipv4(ip):
            candidates.append(ip)
    candidates = candidates[:int(cfg["max_candidates_per_domain"])]
    ok = []
    if candidates:
        with ThreadPoolExecutor(max_workers=min(int(cfg["probe_workers"]), len(candidates))) as pool:
            futures = {pool.submit(probe, domain, ip, cfg): ip for ip in candidates}
            for fu in as_completed(futures):
                r = fu.result()
                if r:
                    ok.append(r)

    def rank(r, need_full=(domain == "github.com")):
        full = need_full and r["body_bytes"] >= FULL_PAGE_MIN_BYTES
        if need_full:
            return (1 if full else 0, -r["latency"], r["body_bytes"])
        return (0, -r["latency"], 0)
    ok.sort(key=rank, reverse=True)
    diag = {"tested": len(candidates), "reachable": len(ok),
            "full_page": bool(ok and ok[0]["body_bytes"] >= FULL_PAGE_MIN_BYTES),
            "doh": ["seed-only"] if domain in SEED_ONLY_DOMAINS else (ips or [])[:4]}
    if ok:
        log.info("%-32s -> %-16s (%sms, HTTP %s)", domain, ok[0]["ip"],
                 int(ok[0]["latency"] * 1000), ok[0]["status"])
        return domain, ok[0]["ip"], diag
    log.warning("%-32s -> 无可用 IP (已测 %d 个, 跳过, 不写入 hosts)", domain, len(candidates))
    return domain, None, diag


def discover(cfg) -> tuple[dict, dict]:
    """返回 (域名->最快可用IP, 诊断信息)。

    9 个域名并发执行, 单轮耗时从各域名串行之和降为最慢域名耗时。
    域名内候选 IP 仍并发探测, 判定口径(整页正文/TLS 校验)保持原样。
    """
    records, diagnostics = {}, {}
    domains = list(cfg["domains"])
    with ThreadPoolExecutor(max_workers=min(6, len(domains))) as pool:
        futs = [pool.submit(_discover_one, d, cfg) for d in domains]
        for fu in as_completed(futs):
            d, ip, diag = fu.result()
            diagnostics[d] = diag
            if ip:
                records[d] = ip
    return records, diagnostics


# ---------------------------------------------------------------- hosts 读写事务

def decode_hosts(raw: bytes) -> tuple[str, str]:
    """精确识别编码, 避免给原本无 BOM 的 hosts 添加 BOM (会破坏首行解析)."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise ValueError("hosts 编码无法识别")


def rebuild_hosts(text: str, records: dict, domains: list[str]) -> tuple[str, int]:
    """保留所有非 GitHub 内容; 删除受管理区块、旧标记行、重复/失效的 GitHub 解析行."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    managed = {d.lower() for d in domains} | set(SEEDS)  # 含已从配置移除的历史域名
    has_end = any(l.strip() == END for l in lines)
    in_block = False
    out, removed = [], 0
    for line in lines:
        s = line.strip()
        if s == BEGIN:
            in_block = has_end
            removed += 1
            continue
        if s == END:
            in_block = False
            removed += 1
            continue
        if in_block:
            removed += 1
            continue
        if s.startswith("# GitHub Start") or s == "# GitHub End":
            removed += 1
            continue
        m = IPV4.match(line)
        if m and m.group(2).lower() in managed:
            removed += 1
            continue
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    block = [BEGIN, f"# updated: {now()} | verified by TLS cert + HTTPS"]
    for d, ip in records.items():
        block.append(f"{ip}    {d}")
    block.append(END)
    return nl.join(out + [""] + block) + nl, removed


def backup_hosts(cfg, raw: bytes) -> Path:
    d = resolve(cfg["backup_dir"])
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"hosts_{datetime.now():%Y%m%d_%H%M%S}.bak"
    p.write_bytes(raw)
    files = sorted(d.glob("hosts_*.bak"))
    for old in files[:-max(1, int(cfg["backup_keep"]))]:
        old.unlink(missing_ok=True)
    log.info("备份: %s", p)
    return p


def write_hosts_bytes(data: bytes):
    """就地覆盖(保留原文件 ACL), 临时解除只读属性后恢复."""
    st = os.stat(HOSTS)
    mode = stat.S_IMODE(st.st_mode)
    readonly = not bool(mode & stat.S_IWRITE)
    if readonly:
        os.chmod(HOSTS, mode | stat.S_IWRITE)
    try:
        with open(HOSTS, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    finally:
        if readonly:
            os.chmod(HOSTS, mode)


def rollback(cfg, original: bytes, backup: Path, reason: str):
    log.error("触发回滚: %s", reason)
    try:
        write_hosts_bytes(original)
        if HOSTS.read_bytes() != original:
            shutil.copyfile(backup, HOSTS)
        log.info("回滚成功, hosts 已还原")
        s = load_state(cfg)
        save_state(cfg, {"total_rollbacks": s.get("total_rollbacks", 0) + 1,
                         "last_rollback": now(), "last_rollback_reason": reason})
    except Exception as e:                           # noqa: BLE001
        log.critical("回滚失败! 请手动用备份还原: %s (%s)", backup, e)


def flush_dns(cfg):
    r, err = with_retries(lambda: subprocess.run(
        ["ipconfig", "/flushdns"], capture_output=True,
        timeout=float(cfg["flushdns_timeout_seconds"]), check=True,
        **hidden_process_kwargs()), cfg, "flushdns")
    if err:
        log.warning("ipconfig /flushdns 失败(不回滚, hosts 已正确): %s", err)
    else:
        log.info("DNS 缓存已刷新")


def apply_hosts(cfg, records: dict) -> dict:
    """带备份/校验/回滚的写入事务."""
    if not is_admin():
        raise PermissionError("需要管理员权限: 右键 run-as-admin.bat -> 以管理员身份运行")
    raw = HOSTS.read_bytes()
    text, enc = decode_hosts(raw)
    new_text, removed = rebuild_hosts(text, records, cfg["domains"])
    new_raw = new_text.encode(enc)
    info = {"changed": new_raw != raw, "removed": removed, "backup": None, "rollback": False}
    if not info["changed"]:
        log.info("hosts 内容无变化, 跳过写入与备份 (清理 %d 行重复/失效条目)", removed)
        flush_dns(cfg)
        return info
    info["backup"] = str(backup_hosts(cfg, raw))
    backup = Path(info["backup"])
    try:
        write_hosts_bytes(new_raw)
        if HOSTS.read_bytes() != new_raw:
            raise OSError("hosts 写入后内容校验失败")
        log.info("hosts 已更新: 写入 %d 条, 清理 %d 行重复/失效条目", len(records), removed)
        flush_dns(cfg)
    except Exception as e:                           # noqa: BLE001
        rollback(cfg, raw, backup, f"写入/校验异常: {e}")
        info["rollback"] = True
        raise
    return info


# ---------------------------------------------------------------- 热路径 (亚秒级故障切换)
#
# 旧架构: 全量 discover 每 10~25 分钟一轮(单轮约 90s), 外部看门狗 2 分钟巡检 +
# 连续 2 次失败 + 3 分钟冷却, IP 失效后需数分钟恢复, 浏览器表现为
# ERR_CONNECTION_TIMED_OUT。
# 新架构: supervisor 内常驻热路径线程, 与慢速全量探测解耦:
#   1) 并发微探测维护 github.com 预热 IP 池(TCP+TLS 校验+响应头+首段正文, 数百 ms)
#   2) 每 500ms 检查当前 hosts IP, 失效即从池内取 RTT 最低的可用 IP
#   3) 增量替换 hosts 单行 + Win32 DnsFlushResolverCache(无子进程), 目标 < 500ms
#   4) 全量 discover 降为池维护, 仍负责其余 8 个域名与整页正文校验
# 对外行为不变: CLI、日志、state/heartbeat、hosts 受管理区块、备份/回滚、
#              不自动打开网页、桌面工具全部保持原样。

def fast_flush_dns(cfg) -> float:
    """Win32 DNS 缓存刷新, 无子进程(通常 <5ms); 不可用则回退 ipconfig。"""
    t0 = time.perf_counter()
    if os.name == "nt":
        try:
            if ctypes.windll.dnsapi.DnsFlushResolverCache() == 0:
                raise OSError("DnsFlushResolverCache 返回 0")
            return (time.perf_counter() - t0) * 1000
        except Exception as e:                          # noqa: BLE001
            log.debug("快速 DNS 刷新不可用, 回退 ipconfig: %s", e)
    flush_dns(cfg)
    return (time.perf_counter() - t0) * 1000


def micro_probe(domain: str, ip: str, timeout_ms: int, connect_ms: int = 400) -> dict:
    """轻量探测: TCP + TLS 证书校验 + 响应头 + 至少 4KB 正文。

    connect_ms 单独设短: 链路被整体阻断时 TCP 握手必然超时, 400ms 即可判死,
    不必等完整 timeout_ms; 正常链路 TCP 约 110ms、TLS 约 250ms, 不会被误伤。
    """
    t0 = time.perf_counter()
    deadline = t0 + timeout_ms / 1000.0

    def left() -> float:
        return max(0.03, deadline - time.perf_counter())

    r = {"ip": ip, "ok": False, "rtt_ms": None}
    try:
        if not ip or not public_ipv4(ip):
            r["reason"] = "invalid_ip"
            return r
        ctx = ssl.create_default_context()             # check_hostname=True, CERT_REQUIRED
        with socket.create_connection((ip, 443), timeout=connect_ms / 1000.0) as raw:
            raw.settimeout(left())
            with ctx.wrap_socket(raw, server_hostname=domain) as s:
                s.settimeout(left())
                s.sendall((f"GET / HTTP/1.1\r\nHost: {domain}\r\n"
                           "User-Agent: GitHubHostsKeeper-HotPath/1.0\r\n"
                           "Accept: */*\r\nConnection: close\r\n\r\n").encode("ascii"))
                head = b""
                while b"\r\n\r\n" not in head and len(head) < 16384 and time.perf_counter() < deadline:
                    s.settimeout(left())
                    c = s.recv(4096)
                    if not c:
                        break
                    head += c
                m = re.search(rb"HTTP/[\d.]+ (\d{3})", head)
                if not m or int(m.group(1)) >= 500:
                    r["reason"] = "bad_status"
                    return r
                body = head.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in head else b""
                while len(body) < HOTPATH_MIN_BODY and time.perf_counter() < deadline:
                    s.settimeout(left())
                    c = s.recv(4096)
                    if not c:
                        break
                    body += c
                if len(body) < HOTPATH_MIN_BODY:
                    r["reason"] = f"正文不完整({len(body)}B)"
                    return r
                r.update({"ok": True, "status": int(m.group(1)), "body_bytes": len(body),
                          "rtt_ms": round((time.perf_counter() - t0) * 1000, 1)})
    except Exception as e:                             # noqa: BLE001
        r["reason"] = classify_error(e)
        r["rtt_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return r


def load_ip_pool(cfg) -> dict:
    p = resolve(cfg["hotpath_pool_path"])
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("entries"), dict):
            return d
    except Exception:                                  # noqa: BLE001
        pass
    return {"entries": {}, "updated_at": None, "active_ip": None, "switches": 0}


def save_ip_pool(cfg, pool: dict):
    p = resolve(cfg["hotpath_pool_path"])
    try:
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:                             # noqa: BLE001
        log.debug("IP 池写入失败(不影响主流程): %s", e)


def pool_candidates(cfg, pool: dict) -> list[str]:
    ips = list(SEEDS.get("github.com", [])) + list(pool["entries"].keys())
    out, seen = [], set()
    for ip in ips:
        if ip not in seen and public_ipv4(ip):
            seen.add(ip)
            out.append(ip)
    return out[:int(cfg["hotpath_pool_size"])]


def refresh_pool(cfg, pool: dict, domain: str, timeout_ms: int) -> list[dict]:
    cands = pool_candidates(cfg, pool)
    connect_ms = int(cfg["hotpath_connect_timeout_ms"])
    with ThreadPoolExecutor(max_workers=min(12, max(1, len(cands)))) as ex:
        results = list(ex.map(lambda ip: micro_probe(domain, ip, timeout_ms, connect_ms), cands))
    entries = pool["entries"]
    for r in results:
        e = entries.setdefault(r["ip"], {"ok": 0, "fail": 0, "rtt_ms": None})
        if r["ok"]:
            e["ok"] += 1
            e["fail"] = 0
            e["rtt_ms"] = r["rtt_ms"]
            e["last_ok"] = now()
        else:
            # 保留 rtt_ms: 间歇阻断时池不能一轮失败就清空, 否则下一刻无备用 IP 可切。
            # 连续失败计数达到阈值后由 best_pool_ip 暂时淘汰, 一旦恢复成功即自动复活。
            e["fail"] = int(e.get("fail", 0)) + 1
            e["last_fail"] = now()
    pool["updated_at"] = now()
    return results


def current_host_ip(domain: str = "github.com") -> str | None:
    try:
        text, _ = decode_hosts(HOSTS.read_bytes())
        for line in text.splitlines():
            m = IPV4.match(line)
            if m and m.group(2).lower() == domain:
                return m.group(1)
    except Exception:                                  # noqa: BLE001
        pass
    return None


def best_pool_ip(cfg, pool: dict, exclude: str | None) -> str | None:
    """选延迟最低的备用 IP; 允许近期有少量失败, 避免间歇阻断时池被判空。"""
    ranked = sorted(
        ((e.get("fail", 0), e.get("rtt_ms"), ip) for ip, e in pool["entries"].items()
         if e.get("rtt_ms") is not None and e.get("fail", 0) <= 2 and ip != exclude),
        key=lambda x: (x[0], x[1]))
    return ranked[0][2] if ranked else None


def switch_domain_ip(cfg, domain: str, new_ip: str) -> dict:
    """增量替换受管理区块内某一行; 带备份/校验/回滚, 其余内容字节不变。"""
    t0 = time.perf_counter()
    if not is_admin():
        return {"ok": False, "reason": "需要管理员权限", "elapsed_ms": 0}
    try:
        raw = HOSTS.read_bytes()
        text, enc = decode_hosts(raw)
        nl = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines()
        in_block, found, out = False, False, []
        for line in lines:
            st = line.strip()
            if st == BEGIN:
                in_block = True
                out.append(line)
                continue
            if st == END:
                if in_block and not found:
                    out.append(f"{new_ip}    {domain}")
                    found = True
                in_block = False
                out.append(line)
                continue
            m = IPV4.match(line)
            if in_block and m and m.group(2).lower() == domain:
                if not found:
                    out.append(f"{new_ip}    {domain}")
                    found = True
                continue
            out.append(line)
        if not found:
            return {"ok": False, "reason": "hosts 无受管理区块, 交由全量流程处理",
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
        new_raw = (nl.join(out) + nl).encode(enc)
        if new_raw == raw:
            return {"ok": True, "changed": False,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
        backup = backup_hosts(cfg, raw)
        try:
            write_hosts_bytes(new_raw)
            if HOSTS.read_bytes() != new_raw:
                raise OSError("hosts 写入后内容校验失败")
        except Exception as e:                         # noqa: BLE001
            rollback(cfg, raw, backup, f"热路径切换异常: {e}")
            return {"ok": False, "reason": str(e),
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
        dns_ms = fast_flush_dns(cfg)
        return {"ok": True, "changed": True, "to": new_ip, "dns_ms": round(dns_ms, 2),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:                             # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}",
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}


def hotpath_once(cfg) -> int:
    """单次热路径检测(验证/手动触发用); 输出 JSON 指标, 绝不打开网页。"""
    domain, t0 = "github.com", time.perf_counter()
    timeout_ms = int(cfg["hotpath_probe_timeout_ms"])
    connect_ms = int(cfg["hotpath_connect_timeout_ms"])
    pool = load_ip_pool(cfg)
    results = refresh_pool(cfg, pool, domain, timeout_ms)
    cur = current_host_ip(domain)
    probe = (micro_probe(domain, cur, timeout_ms, connect_ms) if cur
             else {"ok": False, "reason": "无 hosts 记录"})
    out = {"current_ip": cur, "current_probe": probe,
           "pool": [{"ip": r["ip"], "ok": r["ok"], "rtt_ms": r["rtt_ms"]} for r in results],
           "switched": None, "elapsed_ms": None}
    if not probe["ok"]:
        pick = best_pool_ip(cfg, pool, cur)
        if pick and not CYCLE_RUNNING.is_set():
            out["switched"] = switch_domain_ip(cfg, domain, pick)
            if out["switched"]["ok"]:
                pool["active_ip"] = pick
                pool["switches"] = int(pool.get("switches", 0)) + 1
        elif not pick:
            out["switched"] = {"ok": False, "reason": "池中暂无可用备用 IP"}
    save_ip_pool(cfg, pool)
    out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if probe["ok"] or (out["switched"] and out["switched"]["ok"]) else 4


def hotpath_loop(cfg, stop_event: threading.Event, domain: str = "github.com"):
    """常驻热路径: 池刷新 + 当前 IP 检测 + 亚秒级切换。"""
    interval = float(cfg["hotpath_interval_ms"]) / 1000.0
    timeout_ms = int(cfg["hotpath_probe_timeout_ms"])
    refresh_s = float(cfg["hotpath_pool_refresh_ms"]) / 1000.0
    cooldown = float(cfg["hotpath_switch_cooldown_ms"]) / 1000.0
    threshold = max(1, int(cfg["hotpath_fail_threshold"]))
    connect_ms = int(cfg["hotpath_connect_timeout_ms"])
    backoff_s = float(cfg["hotpath_backoff_ms"]) / 1000.0
    pool = load_ip_pool(cfg)
    failures, last_switch, last_refresh, last_warn = 0, 0.0, 0.0, 0.0
    log.info("热路径启动: 间隔=%sms 探测=%sms/连接=%sms 失败阈值=%s 池刷新=%sms 冷却=%sms 退避=%sms",
             cfg["hotpath_interval_ms"], timeout_ms, connect_ms, threshold,
             cfg["hotpath_pool_refresh_ms"], cfg["hotpath_switch_cooldown_ms"],
             cfg["hotpath_backoff_ms"])
    while not stop_event.is_set():
        tick0 = time.perf_counter()
        degraded = False
        try:
            if tick0 - last_refresh >= refresh_s:
                refresh_pool(cfg, pool, domain, timeout_ms)
                save_ip_pool(cfg, pool)
                last_refresh = time.perf_counter()
            cur = current_host_ip(domain)
            r = (micro_probe(domain, cur, timeout_ms, connect_ms) if cur
                 else {"ok": False, "reason": "无 hosts 记录"})
            if r["ok"]:
                failures = 0
            else:
                failures += 1
                busy, cooling = CYCLE_RUNNING.is_set(), time.perf_counter() - last_switch < cooldown
                if failures >= threshold and not busy and not cooling:
                    pick = best_pool_ip(cfg, pool, cur)
                    if pick:
                        old, sw = cur, switch_domain_ip(cfg, domain, pick)
                        if sw.get("ok"):
                            last_switch = time.perf_counter()
                            failures = 0
                            pool["active_ip"] = pick
                            pool["switches"] = int(pool.get("switches", 0)) + 1
                            pool["last_switch"] = {"at": now(), "from": old, "to": pick,
                                                   "reason": r.get("reason"), **sw}
                            save_ip_pool(cfg, pool)
                            log.info("热路径切换 %s -> %s 耗时 %.1fms (DNS %.2fms, 原因: %s)",
                                     old, pick, sw["elapsed_ms"], sw.get("dns_ms", -1),
                                     r.get("reason"))
                        else:
                            degraded = True
                            log.warning("热路径切换失败: %s", sw.get("reason"))
                    else:
                        # 所有候选 IP 同时不可达 = 网络层整体阻断, 本机无法自愈;
                        # 退避并节流日志, 避免无效连接风暴与日志刷屏。
                        degraded = True
                        if time.perf_counter() - last_warn >= 10:
                            last_warn = time.perf_counter()
                            log.warning("热路径: 当前 IP 不可用且池中无可用备用 IP (%s); "
                                        "属网络层整体阻断, 退避至 %sms 等待链路恢复",
                                        r.get("reason"), cfg["hotpath_backoff_ms"])
        except Exception as e:                         # noqa: BLE001 - 热路径不能拖垮 supervisor
            degraded = True
            log.warning("热路径单轮异常: %s: %s", type(e).__name__, e)
        wait_s = max(0.05, interval - (time.perf_counter() - tick0))
        if degraded:
            wait_s = max(wait_s, backoff_s)
        stop_event.wait(wait_s)


# ---------------------------------------------------------------- 访问验证

def classify_error(e: Exception) -> str:
    if isinstance(e, urllib.error.URLError):       # 拆包, 否则只会显示 "URLError"
        inner = e.reason
        if isinstance(inner, socket.gaierror):
            return "DNS 解析失败"
        if isinstance(inner, (socket.timeout, TimeoutError)):
            return "TLS 握手/连接超时(疑似网络层干扰)"
        if isinstance(inner, (ConnectionResetError, ssl.SSLError, BrokenPipeError)):
            return "TLS/连接被重置(疑似网络层 SNI 干扰)"
        return f"网络不可达: {type(inner).__name__}"
    if isinstance(e, socket.gaierror):
        return "DNS 解析失败"
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "连接超时"
    if isinstance(e, (ConnectionResetError, ssl.SSLError, BrokenPipeError)):
        return "TLS/连接被重置(疑似网络层 SNI 干扰)"
    return type(e).__name__


def check_https(cfg, full_download: bool = False) -> dict:
    """直连检查; full_download=True 时读取正文并判定完整加载耗时(供访问巡检使用).

    默认行为(只读响应头)保持不变, 供 verify() 复用; 巡检必须开启完整读取,
    否则「头通但正文传不下来」会被误判为可用。
    """
    t0 = time.time()
    try:
        req = urllib.request.Request(cfg["verify_url"], headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GitHubHostsKeeper/1.0"})
        # 必须直连: urllib 默认读取 HTTP(S)_PROXY / 系统代理, 走代理时由代理自行解析域名,
        # hosts 记录完全不生效, 且与 probe() 的直连口径不一致, 会把代理不通误判成 SNI 干扰。
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=float(cfg["http_timeout_seconds"])) as r:
            status = r.status
            if full_download:
                body = r.read(CHECK_BODY_LIMIT)
                elapsed = time.time() - t0
                limit = float(cfg["health_check_timeout_seconds"])
                if len(body) < FULL_PAGE_MIN_BYTES:
                    return {"ok": False, "method": "https",
                            "reason": f"页面正文不完整({len(body)}B < {FULL_PAGE_MIN_BYTES}B)",
                            "detail": "疑似头通正文不通的失效 IP", "elapsed": round(elapsed, 3)}
                if elapsed > limit:
                    return {"ok": False, "method": "https",
                            "reason": f"页面加载缓慢({elapsed:.1f}s > {limit:.0f}s)",
                            "detail": "正文读取耗时超限", "elapsed": round(elapsed, 3)}
        return {"ok": True, "status": status, "method": "https",
                "elapsed": round(time.time() - t0, 3)}
    except urllib.error.HTTPError as e:
        return {"ok": True, "status": e.code, "method": "https",
                "note": "服务器有响应(HTTP 4xx/3xx 亦视为连通)"}
    except Exception as e:                           # noqa: BLE001
        return {"ok": False, "method": "https", "reason": classify_error(e),
                "detail": str(e)[:160]}


def open_github_page(cfg) -> int:
    """唯一的网页打开入口, 仅由 --open 触发(必须是用户主动执行).

    自动流程(单轮/守护/看门狗/巡检/计划任务)一律不调用本函数,
    因此不存在任何自动弹出、自动跳转或自行显示网页的行为。
    用系统默认浏览器打开配置的 verify_url, 不启动后台任务, 不修改 hosts。
    """
    url = str(cfg["verify_url"])
    try:
        if os.name == "nt":
            os.startfile(url)                        # noqa: S606 - 由用户显式触发
        else:
            import webbrowser
            webbrowser.open(url)
        log.info("手动打开网页: %s", url)
        print(f"已打开: {url}")
        return 0
    except Exception as e:                           # noqa: BLE001
        log.error("手动打开网页失败: %s", e)
        print(f"[错误] 无法打开 {url}: {e}")
        return 1


def verify(cfg, full: bool = True) -> dict:
    """只做网络层可达性验证; 绝不启动浏览器或显示网页。

    full 参数与 edge 字段保留, 以兼容原有调用签名及 state.json / 日志结构。
    页面级可用性由 check_https() 的完整正文读取口径保障(见 access_check)。
    """
    # full 保留仅为兼容 run_cycle 的调用签名; 不再据此启动任何浏览器。
    # HTTPS 验证口径保持原样; 页面级判定由访问巡检 check_https(full_download=True) 承担。
    edge = {"skipped": True, "ok": False, "opened": False, "headless": None,
            "reason": "自动打开网页已禁用; 仅 --open / open-github.bat 可手动打开"}
    out = {"https": check_https(cfg), "edge": edge, "resolution": {}}
    for d in ("github.com", "api.github.com", "raw.githubusercontent.com"):
        try:
            out["resolution"][d] = socket.gethostbyname(d)
        except Exception as e:                       # noqa: BLE001
            out["resolution"][d] = f"解析失败: {e}"
    # edge.ok 恒为 False: 可达性完全由网络层判定, 浏览器不再参与自动验证。
    out["ok"] = out["https"]["ok"] or out["edge"]["ok"]
    if not out["ok"]:
        log.warning("页面仍不可达: %s", out["https"].get("reason") or out["edge"].get("reason"))
        log.warning("诊断: 若所有 github.com IP 的 TLS 均被重置, 属网络层 SNI 干扰, "
                    "hosts 方案无法解决网页访问, 需使用合规的网络代理; "
                    "但 api/codeload/raw 的 hosts 记录仍可保障 git clone 等操作。")
    else:
        log.info("访问验证通过 (https=%s, 浏览器未启动)", out["https"]["ok"])
    return out


# ---------------------------------------------------------------- 单轮流程

def run_cycle(cfg, dry: bool = False) -> tuple[int, dict]:
    log.info("=" * 62)
    log.info("开始检测 (%s)", now())
    records, diag = discover(cfg)
    # 阻断窗口内整页探测可能全部超时; 本轮无可用 IP 的域名沿用 hosts 中现有的
    # 受管理记录, 避免把原本可用的条目清空、让 DNS 回落到被污染的系统解析。
    try:
        existing, _ = decode_hosts(HOSTS.read_bytes())
        in_block = False
        for line in existing.splitlines():
            s = line.strip()
            if "GitHub Hosts Keeper BEGIN" in s:
                in_block = True
                continue
            if "GitHub Hosts Keeper END" in s:
                in_block = False
                continue
            if not in_block or not s or s.startswith("#"):
                continue
            parts = s.split()
            if (len(parts) >= 2 and parts[1] in cfg["domains"]
                    and parts[1] not in records and public_ipv4(parts[0])):
                records[parts[1]] = parts[0]
                log.info("%-32s -> 沿用现有记录 %s (本轮无可用 IP)", parts[1], parts[0])
    except Exception as e:                              # noqa: BLE001
        log.debug("读取现有 hosts 记录失败: %s", e)
    base = {"last_run": now(), "verified_count": len(records),
            "verified_records": records, "diagnostics": diag}
    if len(records) < int(cfg["min_valid_records"]):
        msg = (f"仅获得 {len(records)} 条可用记录 (阈值 {cfg['min_valid_records']})，"
               "不修改 hosts，保留现有配置")
        log.error(msg)
        save_state(cfg, {**base, "result": "no_valid_records", "message": msg,
                         "consecutive_failures": load_state(cfg).get("consecutive_failures", 0) + 1})
        return 1, {**base, "message": msg}

    text, enc = decode_hosts(HOSTS.read_bytes())
    planned, removed = rebuild_hosts(text, records, cfg["domains"])
    log.info("计划写入 %d 条记录; 将清理 %d 行重复/失效条目; 原有非 GitHub 内容保留",
             len(records), removed)
    if dry:
        print("\n---- DRY RUN: 计划写入的 hosts 区块 (未写入任何文件) ----")
        start = planned.find(BEGIN)
        print(planned[start:] if start >= 0 else planned)
        print("---- DRY RUN END ----\n")
        return 0, {**base, "dry_run": True, "planned_removed": removed}

    try:
        applied = apply_hosts(cfg, records)
    except PermissionError as e:
        log.error("%s", e)
        save_state(cfg, {**base, "result": "permission_denied", "message": str(e)})
        return 2, {**base, "message": str(e)}
    except Exception as e:                           # noqa: BLE001
        log.error("hosts 更新失败(已尝试回滚): %s", e)
        save_state(cfg, {**base, "result": "write_failed", "message": str(e),
                         "consecutive_failures": load_state(cfg).get("consecutive_failures", 0) + 1})
        return 3, {**base, "message": str(e)}

    st = load_state(cfg)
    full = applied["changed"] or st.get("result") != "success"
    v = verify(cfg, full=full)
    if v["ok"]:
        msg = f"更新成功: {len(records)} 条记录, 页面可访问"
        log.info(msg)
        save_state(cfg, {**base, "result": "success", "message": msg,
                         "last_success": now(), "consecutive_failures": 0,
                         "verification": v, "hosts": applied,
                         "total_runs": st.get("total_runs", 0) + 1})
        return 0, {**base, "verification": v, "hosts": applied}
    msg = "hosts 已更新, 但 github.com 页面仍不可达(网络层限制, 详见日志)"
    log.warning(msg)
    save_state(cfg, {**base, "result": "verify_failed", "message": msg,
                     "consecutive_failures": st.get("consecutive_failures", 0) + 1,
                     "verification": v, "hosts": applied,
                     "total_runs": st.get("total_runs", 0) + 1})
    return 4, {**base, "verification": v, "hosts": applied}


# ---------------------------------------------------------------- 看门狗

def ps_quote(s: str) -> str:
    """转成 PowerShell 单引号字面量."""
    return "'" + str(s).replace("'", "''") + "'"


def run_ps(script: str, cfg) -> tuple[bool, str]:
    """执行 PowerShell 片段, 统一超时与异常封装."""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=float(cfg["task_command_timeout_seconds"]),
            **hidden_process_kwargs())
        out = (r.stdout + r.stderr).decode("gbk", "replace").strip()
        return r.returncode == 0 and "OK" in out, out
    except subprocess.TimeoutExpired:
        return False, "PowerShell 命令超时"
    except Exception as e:                           # noqa: BLE001
        return False, f"PowerShell 调用异常: {e}"


def python_exe(cfg) -> str:
    """优先 pythonw.exe(无窗口); cfg 可显式覆盖."""
    if cfg["python_executable"]:
        return cfg["python_executable"]
    p = Path(sys.executable).with_name("pythonw.exe")
    return str(p) if p.exists() else sys.executable


def daemon_health(cfg) -> tuple[bool, str, dict | None]:
    """监控对象: supervisor 进程 + 心跳新鲜度."""
    hb = read_heartbeat(cfg)
    if not hb:
        return False, "无有效心跳文件(守护进程未运行或为旧版本)", None
    age = time.time() - float(hb.get("epoch", 0))
    if age > float(cfg["heartbeat_timeout_seconds"]):
        return False, f"心跳过期 {age:.0f}s > {cfg['heartbeat_timeout_seconds']}s", hb
    pid = int(hb.get("pid") or 0)
    if not pid_alive(pid):
        return False, f"守护进程 PID {pid} 已不存在", hb
    if hb.get("mode") != "supervisor":
        return False, "检测到旧版守护进程(无看门狗心跳)", hb
    return True, f"心跳 {age:.0f}s, PID {pid} 存活", hb


def start_daemon(cfg) -> tuple[bool, str]:
    """恢复策略 1: 通过已注册的高权限任务启动; 策略 2: 直接派生(继承本进程令牌)."""
    ok, out = run_ps(
        f"Start-ScheduledTask -TaskName {ps_quote(cfg['task_name'])}; "
        "if ($?) { 'OK' }", cfg)
    if ok:
        return True, "Start-ScheduledTask"
    log.warning("任务启动失败(%s), 改用直接派生", out[:160])
    try:
        subprocess.Popen(
            [python_exe(cfg), str(Path(__file__).resolve()), "--daemon"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **hidden_process_kwargs())
        return True, "direct Popen (继承当前令牌)"
    except Exception as e:                           # noqa: BLE001
        return False, f"直接派生失败: {e}"


def stop_stale_daemon(cfg, pid) -> bool:
    """僵尸/旧版 supervisor 处理: 严格校验命令行确属本脚本才结束, 否则不动."""
    script_name = Path(__file__).name
    # 非管理员会话常读不到提升进程的 CommandLine, 故允许「进程名为 Python 且命令行不可读」兜底
    ps = (f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' "
          f"-ErrorAction SilentlyContinue; "
          "if ($p -and ($p.Name -eq 'python.exe' -or $p.Name -eq 'pythonw.exe' "
          "-or $p.Name -eq 'py.exe') "
          f"-and (($p.CommandLine -like '*{script_name}*') -or (-not $p.CommandLine))) "
          f"{{ Stop-Process -Id {int(pid)} -Force -ErrorAction SilentlyContinue; 'OK' }}")
    ok, out = run_ps(ps, cfg)
    if ok:
        log.warning("已结束失联的旧守护进程 PID %s", pid)
    else:
        log.warning("未结束 PID %s (身份校验未通过或失败): %s", pid, out[:120])
    return ok


def stop_legacy_daemons(cfg) -> int:
    """升级路径: 无心跳文件时清理旧版守护进程, 否则它占着互斥体会挡住新实例."""
    script_name = Path(__file__).name
    ps = ("$n = 0; Get-CimInstance Win32_Process | Where-Object { "
          "($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe' -or $_.Name -eq 'py.exe') -and "
          f"$_.CommandLine -like '*{script_name}*' -and $_.CommandLine -like '*--daemon*' "
          "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
          "-ErrorAction SilentlyContinue; $n++ }; Write-Output ('KILLED=' + $n + ' OK')")
    ok, out = run_ps(ps, cfg)
    n = 0
    m = re.search(r"KILLED=(\d+)", out)
    if m:
        n = int(m.group(1))
    # 兜底: 旧版 daemon 会把自己的 PID 写进 state.json; 命令行不可读时靠它精确清理
    legacy_pid = load_state(cfg).get("pid")
    try:
        if legacy_pid and int(legacy_pid) != os.getpid() and pid_alive(legacy_pid):
            if stop_stale_daemon(cfg, legacy_pid):
                n += 1
    except Exception:                                # noqa: BLE001
        pass
    log.warning("清理旧版守护进程: %s 个 (CIM=%s)", n, "OK" if ok else out[:120])
    return n


def access_check(cfg, wd: dict, hb: dict | None) -> dict:
    """访问健康巡检: 仅当 supervisor 空闲(无 worker 在跑)时做一次轻量 HTTPS 检查.

    连续失败达到阈值且过冷却期 -> 置 health.trigger, 由现有恢复流程
    结束并重新拉起 supervisor, 新实例启动即执行一轮完整 IP 重探测与 hosts 更新。
    只写状态, 不碰 hosts, 不与 worker 并发。
    """
    h = dict(wd.get("health", {}))
    h["last_check"] = now()
    h["trigger"] = False
    if not cfg["health_check_enabled"]:
        h["last_reason"] = "健康检查已禁用"
        wd["health"] = h
        return wd
    # 旧逻辑在 supervisor 忙时整轮跳过, worker 长时间运行时形成检查空窗,
    # 表现为「进入 GitHub 一段时间后断连却迟迟不恢复」。现在忙时照样检查并累计失败,
    # 只是不触发重启, 等 supervisor 空闲后的下一轮即可立即恢复。
    state = (hb or {}).get("state")
    busy = state != "idle"

    probe_cfg = dict(cfg, http_timeout_seconds=min(
        float(cfg["health_check_timeout_seconds"]), float(cfg["http_timeout_seconds"])))
    r = check_https(probe_cfg, full_download=True)
    h["last_ok"] = bool(r["ok"])
    h["last_reason"] = (f"连通 HTTP {r.get('status')}" if r["ok"]
                        else (r.get("reason") or "未知错误"))
    if r["ok"]:
        h["consecutive_failures"] = 0
        h["last_success"] = now()
    else:
        h["consecutive_failures"] = int(h.get("consecutive_failures", 0)) + 1
    if busy:
        h["last_reason"] += f" (supervisor 忙 state={state}, 本轮只累计不重启)"

    last = h.get("last_trigger_at")
    if last:
        try:
            elapsed = time.time() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S").timestamp()
            cooldown = float(cfg["health_trigger_cooldown_minutes"]) * 60
            if elapsed < cooldown:
                h["last_reason"] += f" (冷却中, 剩余 {int(cooldown - elapsed)}s)"
                wd["health"] = h
                return wd
        except Exception:
            pass

    if not busy and int(h["consecutive_failures"]) >= int(cfg["health_fail_threshold"]):
        h["trigger"] = True
        h["last_trigger_at"] = now()
        h["total_triggers"] = int(h.get("total_triggers", 0)) + 1
        h["consecutive_failures"] = 0
    wd["health"] = h
    return wd


def run_watchdog(cfg) -> int:
    """外部看门狗: 单次检查 + 有限次恢复, 由计划任务每 N 分钟调用."""
    wd = dict(load_state(cfg).get("watchdog", {}))
    wd["last_check"] = now()
    health_triggered = False
    try:
        healthy, reason, hb = daemon_health(cfg)
        if healthy:
            wd = access_check(cfg, wd, hb)
            if not wd["health"]["trigger"]:
                wd.update({"last_action": "none", "last_reason": reason,
                           "consecutive_restarts": 0, "last_error": None})
                update_state(cfg, {"watchdog": wd})
                log.info("看门狗: 健康 (%s; 访问=%s)", reason,
                         wd["health"].get("last_reason"))
                return 0
            reason = f"访问巡检失败: {wd['health']['last_reason']}"
            health_triggered = True
            log.warning("看门狗: %s -> 触发立即刷新", reason)

        log.warning("看门狗: 异常 (%s)", reason)
        if hb is None and cfg["watchdog_kill_stale_daemon"]:
            n = stop_legacy_daemons(cfg)
            if n:
                reason += f"; 已清理 {n} 个旧版守护进程(无心跳)"
                time.sleep(1.5)                  # 等待互斥体随进程退出释放
        cutoff = time.time() - 3600
        times = [t for t in wd.get("restart_times", []) if t > cutoff]
        if len(times) >= int(cfg["watchdog_max_restarts_per_hour"]):
            msg = f"1 小时内已重启 {len(times)} 次, 达到上限, 本轮不再重启"
            wd.update({"last_action": "rate_limited", "last_reason": reason,
                       "last_error": msg, "restart_times": times})
            update_state(cfg, {"watchdog": wd})
            log.error("看门狗: %s", msg)
            return 3

        if cfg["watchdog_kill_stale_daemon"] and hb and hb.get("pid"):
            if pid_alive(hb["pid"]) and stop_stale_daemon(cfg, hb["pid"]):
                time.sleep(1.5)          # 等互斥体释放, 避免新 supervisor 被单实例检查挡掉
        ok, detail = start_daemon(cfg)
        if not health_triggered:
            times.append(time.time())   # 访问巡检触发不占用「失联恢复」的每小时限流额度
        wd.update({"last_action": "restart", "last_reason": reason,
                   "last_start_method": detail, "restart_times": times[-20:],
                   "total_restarts": wd.get("total_restarts", 0) + 1,
                   "consecutive_restarts": wd.get("consecutive_restarts", 0) + 1})
        if not ok:
            wd["last_error"] = detail
            update_state(cfg, {"watchdog": wd})
            log.error("看门狗: 启动失败 (%s)", detail)
            return 3

        time.sleep(float(cfg["watchdog_verify_delay_seconds"]))
        healthy2, reason2, _ = daemon_health(cfg)
        wd["last_verify"] = {"healthy": healthy2, "reason": reason2, "at": now()}
        if healthy2:
            wd.update({"consecutive_restarts": 0, "last_error": None})
            update_state(cfg, {"watchdog": wd})
            log.info("看门狗: 恢复成功 (%s, 方式 %s)", reason2, detail)
            return 0
        wd["last_error"] = f"重启后仍不健康: {reason2}"
        update_state(cfg, {"watchdog": wd})
        log.critical("看门狗: %s", wd["last_error"])
        return 3
    except Exception as e:                           # noqa: BLE001 - 看门狗自身不能崩
        wd.update({"last_action": "exception", "last_error": f"{type(e).__name__}: {e}"})
        try:
            update_state(cfg, {"watchdog": wd})
        except Exception:
            pass
        log.critical("看门狗异常(已记录, 不做破坏性操作): %s", e)
        return 3


def run_worker(cfg) -> tuple[int, str]:
    """内部看门狗: 单轮更新放入子进程, 期间持续心跳; 超时强杀并上报."""
    cmd = [python_exe(cfg), str(Path(__file__).resolve()), "--cycle"]
    t0 = time.time()
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             **hidden_process_kwargs())
    except Exception as e:                           # noqa: BLE001
        return -1, f"worker 启动失败: {e}"
    tick = float(cfg["heartbeat_interval_seconds"])
    limit = float(cfg["cycle_timeout_seconds"])
    while True:
        try:
            return p.wait(timeout=tick), "ok"
        except subprocess.TimeoutExpired:
            write_heartbeat(cfg, state="cycle", worker_pid=p.pid,
                            next_cycle_at="running")
            if time.time() - t0 > limit:
                try:
                    p.kill()
                    p.wait(timeout=10)
                except Exception:                    # noqa: BLE001
                    pass
                return -2, f"worker 超过 {limit:.0f}s 被看门狗终止"


# ---------------------------------------------------------------- 守护 / 任务 / 命令

def acquire_single_instance() -> bool:
    try:
        ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\GitHubHostsKeeper")
        return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def next_interval(cfg, failed: bool) -> float:
    lo, hi = float(cfg["interval_min_minutes"]), float(cfg["interval_max_minutes"])
    base = float(cfg["failure_retry_minutes"]) if failed else random.uniform(lo, hi)
    j = float(cfg["jitter_ratio"])
    return max(60.0, base * 60 * random.uniform(1 - j, 1 + j))


def run_daemon(cfg) -> int:
    """supervisor: 只做调度 + 心跳 + 子进程监控, 不再自己跑业务逻辑."""
    if not acquire_single_instance():
        log.error("已有守护实例在运行, 本次退出")
        return 0
    started = now()
    write_heartbeat(cfg, state="starting", started_at=started)
    log.info("supervisor 启动 PID=%s (间隔 %s~%s 分钟, worker 超时 %ss)",
             os.getpid(), cfg["interval_min_minutes"], cfg["interval_max_minutes"],
             cfg["cycle_timeout_seconds"])
    if cfg.get("hotpath_enabled", True):
        threading.Thread(target=hotpath_loop, args=(cfg, _stop),
                         name="hotpath", daemon=True).start()
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    while not _stop.is_set():
        try:
            cfg = load_config()                    # 热加载: 改配置无需重启
            setup_logging(cfg)
        except Exception as e:                     # noqa: BLE001
            log.error("配置重载失败, 沿用上次配置: %s", e)
        write_heartbeat(cfg, state="cycle", started_at=started)
        CYCLE_RUNNING.set()
        try:
            rc, detail = run_worker(cfg)
        finally:
            CYCLE_RUNNING.clear()
        st = load_state(cfg)
        wd = dict(st.get("watchdog", {}))
        if rc == -2:
            wd["worker_timeouts"] = wd.get("worker_timeouts", 0) + 1
            wd["last_error"] = detail
            log.error("内部看门狗: %s", detail)
        elif rc not in (0, 4):
            wd["worker_failures"] = wd.get("worker_failures", 0) + 1
            wd["last_error"] = detail
            log.error("worker 异常退出 rc=%s (%s)", rc, detail)
        update_state(cfg, {
            "cycle": {"last_exit_code": rc, "last_detail": detail, "last_finished": now()},
            "watchdog": wd,
        })
        wait = next_interval(cfg, failed=rc != 0)
        nxt = datetime.now() + timedelta(seconds=wait)
        update_state(cfg, {"next_run_at": nxt.strftime("%Y-%m-%d %H:%M:%S"),
                           "pid": os.getpid(), "last_exit_code": rc})
        log.info("下次刷新: %s (%.1f 分钟后)", nxt.strftime("%H:%M:%S"), wait / 60)
        remaining = wait
        tick = float(cfg["heartbeat_interval_seconds"])
        while remaining > 0 and not _stop.is_set():
            write_heartbeat(cfg, state="idle", started_at=started,
                            next_cycle_at=nxt.strftime("%Y-%m-%d %H:%M:%S"))
            sl = min(tick, remaining)
            _stop.wait(sl)
            remaining -= sl
    write_heartbeat(cfg, state="stopped", started_at=started)
    log.info("supervisor 已停止")
    return 0


def wd_name(cfg) -> str:
    return cfg["watchdog_task_name"] or (cfg["task_name"] + "-Watchdog")


def install_task(cfg) -> bool:
    """注册主任务(登录自启)+看门狗任务(周期巡检), 同时修正 schtasks 默认设置缺陷."""
    if not is_admin():
        log.error("注册自启任务需要管理员权限")
        return False
    exe = python_exe(cfg)
    script = str(Path(__file__).resolve())
    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$py = {ps_quote(exe)}",
        f"$scr = {ps_quote(script)}",
        '$user = "$env:USERDOMAIN\\$env:USERNAME"',
        "$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest",
        # 修复: PT72H 上限 / 电池策略 / 错过登录不补跑 / 失败不重启
        "$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -StartWhenAvailable "
        "-ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew "
        "-RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)",
        "$a1 = New-ScheduledTaskAction -Execute $py -Argument ('\"{0}\" --daemon' -f $scr)",
        "$t1 = New-ScheduledTaskTrigger -AtLogOn -User $user",
        f"Register-ScheduledTask -TaskName {ps_quote(cfg['task_name'])} -Action $a1 "
        "-Trigger $t1 -Principal $principal -Settings $settings -Force | Out-Null",
    ]
    if cfg["watchdog_enabled"]:
        lines += [
            "$a2 = New-ScheduledTaskAction -Execute $py -Argument ('\"{0}\" --watchdog' -f $scr)",
            f"$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) "
            f"-RepetitionInterval (New-TimeSpan -Minutes {int(cfg['watchdog_interval_minutes'])}) "
            "-RepetitionDuration (New-TimeSpan -Days 3650)",
            f"Register-ScheduledTask -TaskName {ps_quote(wd_name(cfg))} -Action $a2 "
            "-Trigger $t2 -Principal $principal -Settings $settings -Force | Out-Null",
        ]
    lines.append("Write-Output 'OK'")
    ok, out = run_ps("\n".join(lines), cfg)
    if ok:
        log.info("已注册: 主任务 %s (登录自启/最高权限/无 72h 限制), 看门狗任务 %s (每 %s 分钟)",
                 cfg["task_name"], wd_name(cfg) if cfg["watchdog_enabled"] else "(禁用)",
                 cfg["watchdog_interval_minutes"])
    else:
        log.error("注册任务失败: %s", out[:400])
    return ok


def uninstall_task(cfg) -> int:
    names = [cfg["task_name"]]
    if cfg["watchdog_enabled"] or resolve(cfg["heartbeat_path"]).exists():
        names.append(wd_name(cfg))
    ps = "; ".join(
        f"Unregister-ScheduledTask -TaskName {ps_quote(n)} -Confirm:$false -ErrorAction SilentlyContinue"
        for n in names) + "; Write-Output 'OK'"
    ok, out = run_ps(ps, cfg)
    log.info("取消自启: %s", out[:200] if out else names)
    return 0 if ok else 3


def show_status(cfg):
    st = load_state(cfg)
    print("\n===== GitHub Hosts Keeper 状态 =====")
    for k in ("last_run", "last_success", "next_run_at", "result", "message",
              "verified_count", "consecutive_failures", "total_runs", "total_rollbacks"):
        print(f"  {k:22s}: {st.get(k, '-')}")
    healthy, reason, hb = daemon_health(cfg)
    print(f"  {'supervisor 健康':22s}: {'是' if healthy else '否'} ({reason})")
    if hb:
        print(f"  {'心跳':22s}: {hb.get('timestamp')} pid={hb.get('pid')} state={hb.get('state')}")
    cy = st.get("cycle", {})
    if cy:
        print(f"  {'worker 上轮':22s}: rc={cy.get('last_exit_code')} {cy.get('last_detail')}")
    wd = st.get("watchdog", {})
    for k in ("last_check", "last_action", "last_reason", "last_start_method",
              "total_restarts", "consecutive_restarts", "worker_timeouts",
              "worker_failures", "last_error"):
        if wd.get(k) is not None:
            print(f"  watchdog.{k:13s}: {wd.get(k)}")
    hl = wd.get("health", {})
    if hl:
        print(f"  {'访问巡检':22s}: {hl.get('last_check')} ok={hl.get('last_ok')} "
              f"连续失败={hl.get('consecutive_failures', 0)} 触发={hl.get('total_triggers', 0)} "
              f"({hl.get('last_reason')})")
    hp = load_ip_pool(cfg)
    print(f"  {'热路径':22s}: {'启用' if cfg.get('hotpath_enabled', True) else '禁用'} "
          f"切换={hp.get('switches', 0)} 当前={hp.get('active_ip') or current_host_ip() or '-'} "
          f"可用池={sum(1 for e in hp['entries'].values() if e.get('rtt_ms') is not None and e.get('fail', 0) <= 2)}/{len(hp['entries'])}")
    print(f"  {'任务 / 看门狗任务':22s}: {cfg['task_name']} / {wd_name(cfg) if cfg['watchdog_enabled'] else '禁用'}")
    if st.get("verified_records"):
        print("  当前生效记录:")
        for d, ip in st["verified_records"].items():
            print(f"    {ip:16s} {d}")
    try:
        text, _ = decode_hosts(HOSTS.read_bytes())
        n = sum(1 for l in text.splitlines() if IPV4.match(l) and "github" in l.lower())
        print(f"  hosts 中 GitHub 记录行数: {n}")
    except Exception as e:                           # noqa: BLE001
        print(f"  hosts 读取失败: {e}")
    print("  管理员权限:", "是" if is_admin() else "否(写入需管理员)")
    print("=" * 40 + "\n")


def do_rollback(cfg) -> int:
    if not is_admin():
        log.error("回滚需要管理员权限")
        return 2
    d = resolve(cfg["backup_dir"])
    files = sorted(d.glob("hosts_*.bak")) if d.exists() else []
    if not files:
        log.error("没有可用备份")
        return 3
    raw = HOSTS.read_bytes()
    backup = backup_hosts(cfg, raw)
    try:
        write_hosts_bytes(files[-1].read_bytes())
        if not HOSTS.read_bytes():
            raise OSError("还原后 hosts 为空")
        flush_dns(cfg)
        log.info("已从 %s 还原 hosts (还原前状态另存为 %s)", files[-1], backup)
        return 0
    except Exception as e:                           # noqa: BLE001
        rollback(cfg, raw, backup, f"手动还原失败: {e}")
        return 3


def main() -> int:
    ap = argparse.ArgumentParser(description="GitHub Hosts Keeper")
    ap.add_argument("--once", action="store_true", help="单次更新(默认)")
    ap.add_argument("--daemon", action="store_true", help="守护运行(随机间隔)")
    ap.add_argument("--install-task", action="store_true", help="注册登录自启")
    ap.add_argument("--uninstall-task", action="store_true", help="取消登录自启")
    ap.add_argument("--status", action="store_true", help="查看状态")
    ap.add_argument("--dry-run", action="store_true", help="仅探测不写入")
    ap.add_argument("--rollback", action="store_true", help="还原最近备份")
    ap.add_argument("--watchdog", action="store_true", help="看门狗单次检查(周期任务调用)")
    ap.add_argument("--cycle", action="store_true", help="内部: 执行单轮更新")
    ap.add_argument("--open", action="store_true", dest="open_page",
                    help="【手动入口】用默认浏览器打开 GitHub 网页(唯一会显示网页的命令)")
    ap.add_argument("--hotpath-once", action="store_true", dest="hotpath_once",
                    help="热路径单次检测/切换(不打开网页, 输出 JSON 指标)")
    a = ap.parse_args()
    try:
        cfg = load_config()
    except Exception as e:                           # noqa: BLE001
        print(f"[配置错误] {e}")
        return 5
    setup_logging(cfg)
    # 必须最先处理: --open 是唯一会显示网页的分支, 且只由用户主动执行到达。
    if a.open_page:
        return open_github_page(cfg)
    if a.hotpath_once:
        return hotpath_once(cfg)
    if a.status:
        show_status(cfg)
        return 0
    if a.uninstall_task:
        return uninstall_task(cfg)
    if a.rollback:
        return do_rollback(cfg)
    if a.watchdog:
        return run_watchdog(cfg)
    if a.cycle:
        code, _ = run_cycle(cfg)
        return code
    if a.install_task:
        install_task(cfg)
    if a.daemon:
        return run_daemon(cfg)
    if a.dry_run:
        code, _ = run_cycle(cfg, dry=True)
        return code
    code, _ = run_cycle(cfg)
    return code


if __name__ == "__main__":
    sys.exit(main())

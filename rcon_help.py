"""RCON help 回退采集：低层传输、A/B 交换、两阶段编排与严格解析。

仅使用标准库：不 import AstrBot、不写发布目录、不复用 aiomcrcon 的单包连接。
生产入口是 ``MinecraftRCON.scan_help_commands()``：整次扫描持有现有 ``_send_lock``，
只用一条独立 socket 完成；任何失败只关闭扫描 socket，不影响普通命令连接。

设计依据 ``.trellis/tasks/10-25-rcon-help-command-fallback/design.md``，
P0 真机实测形态见同目录 ``research/02-rcon-ab-probe.md``。
"""

from __future__ import annotations

import asyncio
import re
import secrets
import struct
import time
from dataclasses import dataclass

try:  # 以插件包导入（生产）
    from .kb.commands import normalize_entries
except ImportError:  # 以顶层模块导入（tests/ 直接把插件目录放进 sys.path）
    from kb.commands import normalize_entries

SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0

_FRAME_HEAD = 8  # request id + packet type
_FRAME_TAIL = 2  # 两个 NUL 终止字节
_MIN_FRAME_LEN = _FRAME_HEAD + _FRAME_TAIL
_MAX_REQUEST_ID = 1 << 30

# 根命令名与 redirect 目标都只接受 Brigadier literal 的常见字符；
# 真实输出里没有别的形态，出现其它字符说明混淆了错误文本或非标准 help。
_ROOT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_REDIRECT_TARGET_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
# B 哨兵：短、无副作用、不可能被正常注册的命令名；每次扫描带随机后缀。
_B_PREFIX = "rconscanprobe"


class _ScanError(Exception):
    """扫描内部失败（阶段 + 中文原因）。

    只在模块边界被转成 report，不穿透 AstrBot 事件管线；不是可恢复的运行状态，
    也不参与任何调用方分支判断。
    """

    def __init__(self, stage: str, reason: str):
        super().__init__(reason)
        self.stage = stage
        self.reason = reason


@dataclass(frozen=True)
class ScanLimits:
    """扫描预算硬上限：内部常量，不新增用户配置。

    数值来自 design.md §7（P0 实测值上留足余量）；超限一律失败关闭并保留旧快照。
    """

    max_roots: int = 512
    max_packets_per_response: int = 256
    max_response_bytes: int = 1024 * 1024
    max_total_packets: int = 4096
    max_total_bytes: int = 16 * 1024 * 1024
    exchange_timeout: float = 10.0
    total_timeout: float = 300.0
    trailing_window: float = 1.5
    connect_timeout: float = 5.0


def _new_report() -> dict:
    return {
        "ok": False,
        "phase": "connect",
        "root": "",
        "completed_roots": 0,
        "root_count": 0,
        "requests": 0,
        "packets": 0,
        "bytes": 0,
        "elapsed_ms": 0,
        "entries": 0,
        "reason": "",
        "unexpected": False,
    }


class _ScanState:
    """整次扫描的请求数与 id 分配：同一次扫描内 request id 绝不复用。"""

    def __init__(self) -> None:
        self.requests = 0
        self.packets = 0
        self.bytes = 0
        self._next_id = secrets.randbelow(_MAX_REQUEST_ID // 2) + 1
        self._used_ids: set[int] = set()

    def take_id(self) -> int:
        while True:
            rid = self._next_id
            self._next_id += 1
            if self._next_id >= _MAX_REQUEST_ID:
                self._next_id = 1
            if rid not in self._used_ids:
                self._used_ids.add(rid)
                return rid


def _pack_packet(req_id: int, packet_type: int, body: str) -> bytes:
    payload = (
        struct.pack("<ii", req_id, packet_type) + body.encode("utf-8") + b"\x00\x00"
    )
    return struct.pack("<i", len(payload)) + payload


def _check_total_budget(state: _ScanState, limits: ScanLimits) -> None:
    if state.packets > limits.max_total_packets:
        raise _ScanError("budget", f"整次扫描片数超过上限 {limits.max_total_packets}")
    if state.bytes > limits.max_total_bytes:
        raise _ScanError("budget", f"整次扫描字节超过上限 {limits.max_total_bytes}")


async def _send(
    writer: asyncio.StreamWriter, data: bytes, deadline: float, stage: str
) -> None:
    """有界发送；超时抛 asyncio.TimeoutError，连接错误转成 _ScanError。"""
    timeout = deadline - time.monotonic()
    if timeout <= 0:
        raise asyncio.TimeoutError
    try:
        writer.write(data)
        await asyncio.wait_for(writer.drain(), timeout)
    except asyncio.TimeoutError:
        raise
    except (ConnectionResetError, BrokenPipeError, OSError) as exc:
        raise _ScanError(stage, "发送 RCON 请求时连接中断") from exc


async def _read_frame(
    reader: asyncio.StreamReader,
    limits: ScanLimits,
    state: _ScanState,
    stage: str,
    deadline: float,
) -> tuple[int, int, bytes]:
    """读取一个完整 RCON 帧，返回 (request_id, packet_type, body)。

    超时抛 asyncio.TimeoutError 由调用方解释（尾随窗口的静默是正常完成）；
    长度/正文截断、终止字节缺失一律 _ScanError 失败关闭。
    """
    timeout = deadline - time.monotonic()
    if timeout <= 0:
        raise asyncio.TimeoutError
    try:
        header = await asyncio.wait_for(reader.readexactly(4), timeout)
    except asyncio.IncompleteReadError as exc:
        raise _ScanError(stage, "RCON 连接在读取帧长度时中断（EOF/截断）") from exc
    (length,) = struct.unpack("<i", header)
    if length < _MIN_FRAME_LEN or length > limits.max_response_bytes + _MIN_FRAME_LEN:
        raise _ScanError(stage, f"RCON 帧长度非法：{length}")
    timeout = deadline - time.monotonic()
    if timeout <= 0:
        raise asyncio.TimeoutError
    try:
        payload = await asyncio.wait_for(reader.readexactly(length), timeout)
    except asyncio.IncompleteReadError as exc:
        raise _ScanError(stage, "RCON 响应正文截断") from exc
    if payload[-_FRAME_TAIL:] != b"\x00\x00":
        raise _ScanError(stage, "RCON 帧缺少终止字节")
    req_id, packet_type = struct.unpack("<ii", payload[:_FRAME_HEAD])
    state.packets += 1
    state.bytes += len(header) + length
    return req_id, packet_type, payload[_FRAME_HEAD:-_FRAME_TAIL]


async def _authenticate(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    password: str,
    limits: ScanLimits,
    state: _ScanState,
    total_deadline: float,
) -> None:
    auth_id = state.take_id()
    deadline = min(time.monotonic() + limits.exchange_timeout, total_deadline)
    # 认证不计入 2N+4 预算：预算是 help 交换的 A/B 请求数。
    await _send(
        writer, _pack_packet(auth_id, SERVERDATA_AUTH, password), deadline, "auth"
    )
    while True:
        req_id, packet_type, _body = await _read_frame(
            reader, limits, state, "auth", deadline
        )
        if req_id == -1:
            raise _ScanError("auth", "RCON 认证失败（密码错误？）")
        if packet_type == SERVERDATA_AUTH_RESPONSE:
            if req_id != auth_id:
                raise _ScanError("auth", "RCON 认证响应 id 不匹配")
            return
        if packet_type == SERVERDATA_RESPONSE_VALUE:
            # 少数实现先发一个空 RESPONSE_VALUE 再发认证结果，忽略它。
            continue
        raise _ScanError("auth", f"RCON 认证响应类型非法：{packet_type}")


async def _check_trailing(
    reader: asyncio.StreamReader,
    state: _ScanState,
    limits: ScanLimits,
    total_deadline: float,
) -> None:
    """最后一次 B 后的有界尾随窗口：静默到期=检查完成，收到任何包=失败。"""
    deadline = min(time.monotonic() + limits.trailing_window, total_deadline)
    try:
        await _read_frame(reader, limits, state, "trailing", deadline)
    except asyncio.TimeoutError:
        return
    raise _ScanError("trailing", "最后一次 B 后仍收到尾随包")


async def _exchange(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    command: str,
    state: _ScanState,
    limits: ScanLimits,
    total_deadline: float,
    is_last: bool,
) -> str:
    """执行一次 A/B 交换，返回 A 的完整响应文本。

    A 首包（合法空包也算）到达前绝不发送 B；收到 B 才算 A 的响应发送序列结束。
    最后一次交换额外做尾随窗口检查。
    """
    a_id = state.take_id()
    b_id = state.take_id()
    now = time.monotonic()
    # 给最后一次检查预留尾随窗口，避免扫描在收尾前把总预算用光。
    exchange_deadline = min(
        now + limits.exchange_timeout, total_deadline - limits.trailing_window
    )
    if exchange_deadline - now < 0.05:
        raise _ScanError("budget", "总扫描预算不足以再完成一次 help 交换")
    stage = "final_help" if is_last else "help"

    state.requests += 1
    await _send(
        writer,
        _pack_packet(a_id, SERVERDATA_EXECCOMMAND, command),
        exchange_deadline,
        stage,
    )
    req_id, packet_type, first = await _read_frame(
        reader, limits, state, stage, exchange_deadline
    )
    if packet_type != SERVERDATA_RESPONSE_VALUE:
        raise _ScanError(stage, f"help 响应包类型非法：{packet_type}")
    if req_id == b_id:
        raise _ScanError(stage, "A 首包到达前就收到 B 哨兵响应")
    if req_id != a_id:
        raise _ScanError(stage, f"A 首包前收到错/未知 id：{req_id}")
    if len(first) > limits.max_response_bytes:
        raise _ScanError(
            "budget", f"单次 help 响应字节超过上限 {limits.max_response_bytes}"
        )
    _check_total_budget(state, limits)

    chunks = [first]
    packets = 1
    size = len(first)
    state.requests += 1
    sentinel = f"{_B_PREFIX}_{b_id}_{secrets.token_hex(4)}"
    await _send(
        writer,
        _pack_packet(b_id, SERVERDATA_EXECCOMMAND, sentinel),
        exchange_deadline,
        stage,
    )
    while True:
        req_id, packet_type, body = await _read_frame(
            reader, limits, state, stage, exchange_deadline
        )
        _check_total_budget(state, limits)
        if req_id == a_id:
            if packet_type != SERVERDATA_RESPONSE_VALUE:
                raise _ScanError(stage, f"help 响应包类型非法：{packet_type}")
            chunks.append(body)
            packets += 1
            size += len(body)
            if packets > limits.max_packets_per_response:
                raise _ScanError(
                    "budget",
                    f"单次 help 响应片数超过上限 {limits.max_packets_per_response}",
                )
            if size > limits.max_response_bytes:
                raise _ScanError(
                    "budget",
                    f"单次 help 响应字节超过上限 {limits.max_response_bytes}",
                )
            continue
        if req_id == b_id:
            break
        raise _ScanError(stage, f"help 交换中收到错/未知 id：{req_id}")

    try:
        text = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _ScanError(stage, "help 响应不是合法 UTF-8") from exc
    if is_last:
        await _check_trailing(reader, state, limits, total_deadline)
    return text


# ------------------------------------------------------------------ 严格解析


def _split_usage_lines(text: str, label: str) -> list[str]:
    """按 "/" 切出候选 usage 行（不依赖换行），并校验整段文本没有可疑前缀。

    真实输出是每行以 "/" 开头、行间可能用换行分隔；这里对两种形态一视同仁：
    第一个 "/" 之前必须是空白，切出的每段空白归一后作为一行。
    """
    if not isinstance(text, str) or not text.strip():
        raise _ScanError("parse", f"{label} 响应为空")
    head, *chunks = text.split("/")
    if head.strip():
        raise _ScanError("parse", f"{label} 响应不以 / 开头或含无法解析的前缀")
    lines = []
    for chunk in chunks:
        line = " ".join(chunk.split())
        if line:
            lines.append(line)
    if not lines:
        raise _ScanError("parse", f"{label} 响应没有可解析的 usage 行")
    return lines


def _split_redirect(line: str) -> tuple[str, str | None]:
    """把 ``-> target`` 从 usage 中拆出；裸 ``->``（允许尾部空白）归一为 ``...``。"""
    if "->" not in line:
        return line, None
    before, _, after = line.partition("->")
    syntax = before.strip()
    target = after.strip()
    if not syntax:
        raise _ScanError("parse", f"redirect 行缺少左侧命令名：{line[:40]!r}")
    if not target:
        return syntax, "..."
    if " " in target:
        raise _ScanError("parse", f"redirect 目标含多余内容：{line[:40]!r}")
    if not _REDIRECT_TARGET_RE.match(target):
        raise _ScanError("parse", f"redirect 目标形态非法：{target[:40]!r}")
    return syntax, target


def parse_root_help(text: str) -> tuple[list[str], dict[str, str]]:
    """解析根级 ``help``，返回 (根命令列表, 根 redirect 映射)。

    只用于发现根集合与显式根 redirect；根级行不产生普通 usage 条目。
    缺少原版 ``help`` 根、重复根、非 literal 结构一律失败关闭。
    """
    lines = _split_usage_lines(text, "根 help")
    roots: list[str] = []
    redirects: dict[str, str] = {}
    for line in lines:
        token = line.split(" ")[0]
        if not _ROOT_NAME_RE.match(token):
            raise _ScanError("parse", f"根 help 行不是命令结构：{line[:40]!r}")
        if token in redirects or token in roots:
            raise _ScanError("parse", f"根 help 出现重复根：{token}")
        redirect = _root_redirect(line, token)
        roots.append(token)
        if redirect is not None:
            redirects[token] = redirect
    if "help" not in roots:
        raise _ScanError("parse", "根 help 缺少原版 help 根（可能是非标准 help 输出）")
    return roots, redirects


def _root_redirect(line: str, token: str) -> str | None:
    syntax, target = _split_redirect(line)
    if target is None:
        return None
    if syntax != token:
        raise _ScanError("parse", f"根 redirect 行含无法确认的 usage：{line[:40]!r}")
    return target


def parse_targeted_help(text: str, root: str) -> list[dict]:
    """解析 ``help <root>``，返回该根的普通 usage/redirect 条目（可为空）。

    空响应合法：表示没有可见一级子命令，产生零条目，不回填纯根。
    非 redirect 的裸根行、别的前缀、混入的错误文本都失败关闭。
    """
    if not text.strip():
        return []
    entries = []
    for line in _split_usage_lines(text, f"help {root}"):
        token = line.split(" ")[0]
        if token != root:
            raise _ScanError("parse", f"help {root} 返回了其它根：{token}")
        syntax, redirect = _split_redirect(line)
        if syntax == root and redirect is None:
            raise _ScanError("parse", f"help {root} 返回裸根行，无法确认一级 usage")
        entries.append(_usage_entry(root, syntax, redirect))
    return entries


def build_snapshot(entries: list[dict]) -> dict:
    """按共享规则去重稳定排序，构造未写盘的 rcon 快照。"""
    normalized = normalize_entries(entries)
    return {
        "kind": "commands",
        "schema_version": 1,
        "producer": "rcon",
        "count": len(normalized),
        "entries": normalized,
    }


def _usage_entry(root: str, syntax: str, redirect: str | None) -> dict:
    """构造一条 RCON 快照条目（source/level 固定未知，不推断权限或 modid）。"""
    entry = {"name": root, "syntax": syntax, "source": "unknown", "level": None}
    if redirect is not None:
        entry["redirect"] = redirect
    return entry


# ------------------------------------------------------------------ 编排


async def _close_writer(writer: asyncio.StreamWriter | None) -> None:
    """有界关闭扫描 socket；close/wait_closed 的失败只做 best-effort 清理。"""
    if writer is None:
        return
    try:
        writer.close()
    except Exception:
        pass
    try:
        await asyncio.wait_for(writer.wait_closed(), 2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
        pass


async def scan_help(
    host: str,
    port: int,
    password: str,
    limits: ScanLimits | None = None,
) -> tuple[dict | None, dict]:
    """两阶段采集：首次根 help → N 个 targeted → 末次根 help → 汇总快照。

    Returns:
        (snapshot, report)：成功时 snapshot 为未写盘的 rcon 快照、report.ok 为 True；
        失败时 snapshot 为 None，report 含阶段/失败根/进度/请求/片/字节/耗时/原因。
    """
    limits = limits or ScanLimits()
    state = _ScanState()
    report = _new_report()
    started = time.monotonic()
    total_deadline = started + limits.total_timeout
    writer: asyncio.StreamWriter | None = None
    try:
        report["phase"] = "connect"
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), limits.connect_timeout
            )
        except (asyncio.TimeoutError, OSError) as exc:
            raise _ScanError("connect", f"无法连接 RCON {host}:{port}") from exc

        report["phase"] = "auth"
        await _authenticate(reader, writer, password, limits, state, total_deadline)

        report["phase"] = "root_help"
        first_text = await _exchange(
            reader, writer, "help", state, limits, total_deadline, is_last=False
        )
        roots, root_redirects = parse_root_help(first_text)
        report["root_count"] = len(roots)
        if len(roots) > limits.max_roots:
            raise _ScanError(
                "budget",
                f"根命令数 {len(roots)} 超过上限 {limits.max_roots}",
            )
        expected_requests = 2 * (len(roots) + 2)

        entries = [
            _usage_entry(root, root, root_redirects[root])
            for root in roots
            if root in root_redirects
        ]
        report["phase"] = "help"
        for root in roots:
            if state.requests + 2 > expected_requests:
                raise _ScanError("budget", f"请求数将超过预算 2N+4（N={len(roots)}）")
            report["root"] = root
            text = await _exchange(
                reader,
                writer,
                f"help {root}",
                state,
                limits,
                total_deadline,
                is_last=False,
            )
            entries.extend(parse_targeted_help(text, root))
            report["completed_roots"] += 1

        report["phase"] = "final_help"
        report["root"] = ""
        final_text = await _exchange(
            reader, writer, "help", state, limits, total_deadline, is_last=True
        )
        final_roots, _final_redirects = parse_root_help(final_text)
        if set(final_roots) != set(roots):
            added = sorted(set(final_roots) - set(roots))
            vanished = sorted(set(roots) - set(final_roots))
            raise _ScanError(
                "root_set",
                f"首末根集合不一致（新增 {added[:5]}，消失 {vanished[:5]}）",
            )

        snapshot = build_snapshot(entries)
        if snapshot["count"] == 0:
            raise _ScanError(
                "empty", "没有可发布的一级/redirect 证据（RCON 纯根可能未收录）"
            )
        report["ok"] = True
        report["phase"] = "done"
        report["entries"] = snapshot["count"]
        return snapshot, report
    except _ScanError as exc:
        report["phase"] = exc.stage
        report["reason"] = exc.reason
        return None, report
    except asyncio.TimeoutError:
        # 交换/发送超时：不重发、不续读，只关闭扫描 socket 并保留旧快照。
        report["reason"] = f"等待 RCON 响应超时（阶段：{report['phase']}）"
        return None, report
    except asyncio.CancelledError:
        report["phase"] = "cancelled"
        report["reason"] = "扫描已被取消（插件卸载/重载）"
        raise
    except Exception as exc:  # 意外异常只在边界转成回执，堆栈由调用方记录
        report["unexpected"] = True
        report["reason"] = f"扫描异常：{exc}"
        return None, report
    finally:
        report["requests"] = state.requests
        report["packets"] = state.packets
        report["bytes"] = state.bytes
        report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        await _close_writer(writer)

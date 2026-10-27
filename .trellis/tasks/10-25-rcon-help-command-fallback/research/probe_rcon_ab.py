#!/usr/bin/env python3
"""P0 RCON A/B 探针（隔离副本真机实测）。

只发送只读命令（help / help <root> / help help / help 1 / 未知命令 / list），
不执行任何有状态或破坏性 MC 命令；脚本从副本 server.properties 读取 RCON
端口与密码，任何输出与证据文件都不打印密码。
"""

import argparse
import asyncio
import io
import json
import os
import random
import socket
import struct
import sys
import time

TYPE_AUTH = 3
TYPE_EXEC = 2
TYPE_RESP = 0
PLUGIN_DIR = "/home/guigui/code/AstrBot/data/plugins/astrbot_plugin_mc_manager"
ASTRBOT_ROOT = "/home/guigui/code/AstrBot"


def read_props(copy_dir):
    props = {}
    with io.open(os.path.join(copy_dir, "server.properties"), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            props[k] = v
    return props


def frame(rid, ptype, body):
    payload = struct.pack("<ii", rid, ptype) + body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


class RawRcon:
    """最小 RCON framing 实现，保留每次 recv 的原始块大小与包时间线。"""

    def __init__(self, host, port, password, connect_timeout=5.0):
        self.host = host
        self.port = port
        self.password = password
        self.sock = None
        self.buf = b""
        self.chunks = []
        self.connect_timeout = connect_timeout

    def connect(self):
        t0 = time.monotonic()
        self.t_start = t0
        self.buf = b""
        self.chunks = []
        self.sock = socket.create_connection((self.host, self.port), self.connect_timeout)
        self.sock.settimeout(0.2)
        rid = random.randint(1000, 4_000_000)
        self.sock.sendall(frame(rid, TYPE_AUTH, self.password))
        deadline = t0 + self.connect_timeout
        while time.monotonic() < deadline:
            for pkt in self._pump(deadline):
                if pkt["rid"] == -1:
                    raise RuntimeError("RCON 认证失败")
                if pkt["rid"] == rid:
                    return {"auth_rs": round((time.monotonic() - t0) * 1000, 2),
                            "auth_echo": pkt["rid"]}
        raise TimeoutError("RCON 认证超时")

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _pump(self, deadline):
        """从 socket 读一块并解析出完整帧；返回本次解析出的包列表。"""
        out = []
        while True:
            while len(self.buf) >= 4:
                (length,) = struct.unpack("<i", self.buf[:4])
                if length < 10 or length > 1_048_576:
                    raise RuntimeError(f"非法帧长度 {length}")
                if len(self.buf) < 4 + length:
                    break
                body_raw = self.buf[4:4 + length]
                self.buf = self.buf[4 + length:]
                rid, ptype = struct.unpack("<ii", body_raw[:8])
                text = body_raw[8:-2].decode("utf-8", "replace")
                out.append({"rid": rid, "type": ptype, "text": text,
                            "bytes": len(body_raw), "chars": len(text),
                            "t": round(time.monotonic() - self.t_start, 3)})
            if out:
                return out
            if time.monotonic() >= deadline:
                return out
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise ConnectionError("服务端关闭了 socket")
            self.chunks.append(len(chunk))
            self.buf += chunk

    def exchange(self, cmd, a_id, b_id, a_wait=1.5, b_wait=8.0,
                 trailing=0.0, allow_no_a=False):
        """A 首包后发 B 的受控交换；返回结构化时间线。"""
        rec = {"cmd": cmd, "a_id": a_id, "b_id": b_id, "anomalies": []}
        self.t_start = time.monotonic()
        self.buf = b""
        t0 = self.t_start
        self.sock.sendall(frame(a_id, TYPE_EXEC, cmd))
        rec["t_send_a"] = 0.0
        a_packets = []
        first_a_at = None
        b_sent_at = None
        b_text = None
        # 阶段 1：等 A 首包
        deadline = t0 + a_wait
        while first_a_at is None and time.monotonic() < deadline:
            for pkt in self._pump(deadline):
                if pkt["rid"] == a_id:
                    first_a_at = pkt["t"]
                    a_packets.append(pkt)
                elif pkt["rid"] == b_id:
                    rec["anomalies"].append("B 早于 A 首包到达")
                else:
                    rec["anomalies"].append(f"未知 id 首包 {pkt['rid']}")
        if first_a_at is None:
            if not allow_no_a:
                rec["ok"] = False
                rec["error"] = "A 首包超时"
                return rec
            rec["no_a_packet"] = True
            b_sent_at = time.monotonic() - t0
            self.sock.sendall(frame(b_id, TYPE_EXEC, self._b_payload(b_id)))
        else:
            b_sent_at = time.monotonic() - t0
            self.sock.sendall(frame(b_id, TYPE_EXEC, self._b_payload(b_id)))
        rec["t_send_b"] = round(b_sent_at, 3)
        # 阶段 2：收完 A，直到 B
        deadline = t0 + b_sent_at + b_wait
        got_b = False
        while not got_b and time.monotonic() < deadline:
            for pkt in self._pump(deadline):
                if pkt["rid"] == a_id:
                    # A packets before B are the expected multi-packet sequence.
                    a_packets.append(pkt)
                elif pkt["rid"] == b_id:
                    got_b = True
                    b_text = pkt["text"]
                    rec["t_recv_b"] = pkt["t"]
                else:
                    rec["anomalies"].append(f"未知 id 尾包 {pkt['rid']}")
        if not got_b:
            rec["ok"] = False
            rec["error"] = "B 未在超时内到达"
            return rec
        # This probe records trailing packets for review; product failure policy is separate.
        rec["trailing"] = []
        if trailing > 0:
            d = time.monotonic() + trailing
            while time.monotonic() < d:
                for pkt in self._pump(d):
                    rec["trailing"].append({k: pkt[k] for k in ("rid", "bytes", "chars", "t")})
        body = "".join(p["text"] for p in a_packets)
        rec.update({
            "ok": True,
            "a_packets": [{k: p[k] for k in ("bytes", "chars", "t")} for p in a_packets],
            "a_packet_count": len(a_packets),
            "a_bytes": sum(p["bytes"] for p in a_packets),
            "a_chars": len(body),
            "a_empty": (len(a_packets) == 1 and a_packets[0]["chars"] == 0),
            "rtt_a_ms": round((first_a_at - 0.0) * 1000, 2) if first_a_at is not None else None,
            # Packet timestamps are rounded to milliseconds; clamp tiny negative deltas.
            "rtt_b_ms": round(max(0.0, rec["t_recv_b"] - b_sent_at) * 1000, 2),
            "b_text_ignored": (b_text or "")[:120],
            "body": body[:20000],
            "chunks": self.chunks[:50],
        })
        return rec

    @staticmethod
    def _b_payload(rid):
        return "probe_b_%d_%06x" % (rid, random.randint(0, 0xFFFFFF))


def split_roots(text):
    """从根级 help 文本提取根命令名。两种切分都记录，避免假设换行存在。"""
    roots_nl = []
    for line in text.replace("\r", "\n").split("\n"):
        line = line.strip()
        if line.startswith("/"):
            name = line[1:].split(" ")[0].split("\t")[0]
            if name and name not in roots_nl:
                roots_nl.append(name)
    roots_slash = []
    token = ""
    for ch in text:
        if ch == "/":
            token = ""
            continue
        if ch.isspace():
            if token and token not in roots_slash:
                roots_slash.append(token)
            token = ""
            continue
        token += ch
    return roots_nl, roots_slash


def neg_test(host, port, password):
    """负面试验：不发 A 首包即立即连写 A+B，记录真实表现。"""
    conn = RawRcon(host, port, password)
    out = {}
    try:
        conn.connect()
        a_id, b_id = 900001, 900002
        conn.t_start = time.monotonic()
        conn.buf = b""
        conn.chunks = []
        conn.sock.sendall(frame(a_id, TYPE_EXEC, "help"))
        conn.sock.sendall(frame(b_id, TYPE_EXEC, "probe_b_neg_%d" % b_id))
        deadline = time.monotonic() + 2.5
        seen = []
        mismatches = 0
        while time.monotonic() < deadline:
            for pkt in conn._pump(deadline):
                seen.append({k: pkt[k] for k in ("rid", "type", "bytes", "chars", "t")})
                if pkt["rid"] not in (a_id, b_id):
                    mismatches += 1
        out = {"chunks": conn.chunks[:50], "packets": seen[:20],
               "packet_count": len(seen), "unknown_ids": mismatches,
               "first_rid_order": [p["rid"] for p in seen[:20]]}
    except Exception as exc:  # noqa: BLE001 - 负面试验要记录任何异常
        out = {"error": f"{type(exc).__name__}: {exc}", "chunks": list(conn.chunks)[:50]}
    finally:
        conn.close()
    return out


def concurrent_clients(host, port, password, rounds=5, full_help_chars=None):
    """双客户端只读竞争探针：分别记录跨 ID 和同 ID 重复响应。"""
    import select

    c1 = RawRcon(host, port, password)
    c2 = RawRcon(host, port, password)
    out = {"rounds": rounds, "observations": [], "anomalies": [],
           "same_id_duplicate_rounds": []}
    try:
        c1.connect()
        c2.connect()
        for r in range(rounds):
            c1.t_start = time.monotonic()
            c2.t_start = c1.t_start
            c1.buf = c2.buf = b""
            c1.chunks = []
            c2.chunks = []
            id1, id2 = 300001 + r * 2, 300002 + r * 2
            c1.sock.sendall(frame(id1, TYPE_EXEC, "help"))
            c2.sock.sendall(frame(id2, TYPE_EXEC, "help"))
            seen = {1: [], 2: []}
            deadline = time.monotonic() + 8.0
            silence = 0.5
            last_packet = time.monotonic()
            while time.monotonic() < deadline:
                ready, _, _ = select.select([c1.sock, c2.sock], [], [], 0.05)
                if not ready:
                    if time.monotonic() - last_packet > silence:
                        break
                    continue
                for sock in ready:
                    conn, mine, other = (c1, 1, 2) if sock is c1.sock else (c2, 2, 1)
                    try:
                        chunk = sock.recv(65536)
                    except socket.timeout:
                        continue
                    if not chunk:
                        out["anomalies"].append(f"round {r}: conn{mine} closed")
                        continue
                    conn.chunks.append(len(chunk))
                    conn.buf += chunk
                    while len(conn.buf) >= 4:
                        (length,) = struct.unpack("<i", conn.buf[:4])
                        if len(conn.buf) < 4 + length:
                            break
                        raw = conn.buf[4:4 + length]
                        conn.buf = conn.buf[4 + length:]
                        rid, ptype = struct.unpack("<ii", raw[:8])
                        text = raw[8:-2].decode("utf-8", "replace")
                        seen[mine].append({"rid": rid, "chars": len(text)})
                        last_packet = time.monotonic()
                        expected = id1 if mine == 1 else id2
                        if rid not in (expected,):
                            out["anomalies"].append(
                                f"round {r}: conn{mine} 收到非本方 id {rid}（本方 {expected}）")
            observation = {
                "round": r, "id1": id1, "id2": id2,
                "conn1_ids": [p["rid"] for p in seen[1]],
                "conn2_ids": [p["rid"] for p in seen[2]],
                "conn1_chars": sum(p["chars"] for p in seen[1]),
                "conn2_chars": sum(p["chars"] for p in seen[2]),
            }
            for conn_no, expected in ((1, id1), (2, id2)):
                same_packets = sum(p["rid"] == expected for p in seen[conn_no])
                same_chars = sum(p["chars"] for p in seen[conn_no]
                                 if p["rid"] == expected)
                observation[f"conn{conn_no}_same_id_packets"] = same_packets
                observation[f"conn{conn_no}_same_id_chars"] = same_chars
                if full_help_chars:
                    copies, remainder = divmod(same_chars, full_help_chars)
                    observation[f"conn{conn_no}_estimated_response_copies"] = copies
                    observation[f"conn{conn_no}_response_remainder_chars"] = remainder
                    if copies >= 2 and remainder == 0:
                        out["same_id_duplicate_rounds"].append({
                            "round": r, "conn": conn_no, "copies": copies,
                            "chars": same_chars,
                        })
            out["observations"].append(observation)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        c1.close()
        c2.close()
    return out


async def plugin_checks(host, port, password, full_help_chars):
    """用插件现有 MinecraftRCON 验证：长响应单包截断与后续命令污染、共享锁。"""
    sys.path.insert(0, ASTRBOT_ROOT)
    sys.path.insert(0, PLUGIN_DIR)
    os.chdir(ASTRBOT_ROOT)
    from rcon_client import MinecraftRCON  # noqa: PLC0415

    result = {"import": "ok"}
    rc = MinecraftRCON(host, port, password)
    try:
        t0 = time.monotonic()
        first = await rc.execute_async("help")
        result["help_via_plugin"] = {
            "returned_chars": len(first),
            "looks_truncated": full_help_chars and len(first) < full_help_chars,
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 2),
            "head": first[:160],
        }
        t1 = time.monotonic()
        after = await rc.execute_async("list")
        looks_like_list = ("players online" in after.lower()
                           or "there are" in after.lower()
                           or after.strip() == "命令执行成功（无返回信息）")
        result["list_after_plugin_help"] = {
            "elapsed_ms": round((time.monotonic() - t1) * 1000, 2),
            "head": after[:200],
            "looks_like_list": looks_like_list,
            # A non-list response after help is residual contamination, regardless of its head.
            "contaminated": not looks_like_list,
        }
    except Exception as exc:  # noqa: BLE001
        result["plugin_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await rc.close()

    rc2 = MinecraftRCON(host, port, password)
    try:
        raw = RawRcon(host, port, password)
        holder = {}

        def scan_in_thread():
            raw.connect()
            try:
                holder["scan"] = raw.exchange("help", 810001, 810002,
                                              a_wait=2.0, b_wait=10.0, trailing=0.3)
                holder["scan_done_at"] = time.monotonic()
            finally:
                raw.close()

        t_lock = time.monotonic()
        async with rc2._send_lock:
            holder["lock_held_at"] = time.monotonic() - t_lock
            task = asyncio.create_task(rc2.execute_async("list"))
            await asyncio.to_thread(scan_in_thread)
            holder["lock_releasing_at"] = time.monotonic() - t_lock
        t = time.monotonic()
        listed = await task
        result["shared_lock"] = {
            "lock_held_s": round(holder.get("lock_releasing_at", 0), 2),
            "scan_ok": holder.get("scan", {}).get("ok"),
            "scan_a_chars": holder.get("scan", {}).get("a_chars"),
            "list_wait_after_lock_ms": round((time.monotonic() - t) * 1000, 2),
            "list_head": listed[:160],
            "list_correct": ("players online" in listed.lower()
                             or "there are" in listed.lower()
                             or "无返回信息" in listed),
        }
    except Exception as exc:  # noqa: BLE001
        result["shared_lock_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await rc2.close()
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", required=True, help="副本目录")
    ap.add_argument("--out", required=True, help="证据 JSON 输出路径")
    ap.add_argument("--scan", action="store_true", help="执行全量 2N+4 正式扫描")
    ap.add_argument("--max-roots", type=int, default=400)
    ap.add_argument("--trailing", type=float, default=2.0)
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)  # plugin_checks 会 chdir，先定住绝对路径

    props = read_props(args.copy)
    host = "127.0.0.1"
    port = int(props["rcon.port"])
    password = props["rcon.password"]
    name = os.path.basename(args.copy.rstrip("/"))

    ev = {"copy": name, "host": host, "port": port, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
          "args": {"scan": args.scan, "trailing": args.trailing}, "phases": {}}

    # 1. 负面试验
    ev["phases"]["negative_immediate_ab"] = neg_test(host, port, password)

    # 2. 正式扫描（或抽样）
    conn = RawRcon(host, port, password)
    conn.connect()
    ids = iter(range(500000, 900000))  # 整次扫描复用一个 id 序列，保证不复用
    try:
        scan_wall_t0 = time.monotonic()
        first = conn.exchange("help", next(ids), next(ids), a_wait=3.0, b_wait=15.0)
        ev["phases"]["initial_help"] = {k: first[k] for k in first
                                        if k not in ("body", "chunks")}
        roots_nl, roots_slash = split_roots(first.get("body", ""))
        ev["phases"]["root_parse"] = {"roots_by_newline": len(roots_nl),
                                      "roots_by_slash": len(roots_slash),
                                      "sample": roots_nl[:12]}
        roots = roots_nl or roots_slash
        roots = roots[:args.max_roots]
        ev["root_count_N"] = len(roots)
        ev["budget_requests_2Nplus4"] = 2 * (len(roots) + 2)

        targets = []
        if args.scan:
            targets = roots
        else:
            for cand in ("execute", "wine", "list", "help", "advancement"):
                if cand in roots:
                    targets.append(cand)
            if roots and roots[0] not in targets:
                targets.append(roots[0])
        samples = {}
        empty_roots = []
        redirect_roots = []
        used_no_packet = []
        targeted_loop_t0 = time.monotonic()
        for root in targets:
            rec = conn.exchange(f"help {root}", next(ids), next(ids), a_wait=1.5, b_wait=10.0,
                                trailing=0.0, allow_no_a=True)
            if rec.get("no_a_packet"):
                used_no_packet.append(root)
            elif rec.get("ok") and rec.get("a_empty"):
                empty_roots.append(root)
            body = rec.get("body") or ""
            if "->" in body:
                redirect_roots.append(root)
            if root not in samples or rec.get("a_chars", 0) > samples[root].get("a_chars", 0):
                samples[root] = {
                    "ok": rec.get("ok"),
                    "a_chars": rec.get("a_chars", 0),
                    "a_bytes": rec.get("a_bytes", 0),
                    "a_packet_count": rec.get("a_packet_count", 0),
                    "rtt_b_ms": rec.get("rtt_b_ms"),
                    "no_a_packet": rec.get("no_a_packet", False),
                    "a_empty": rec.get("a_empty", False),
                    "error": rec.get("error"),
                    "anomalies": rec.get("anomalies", []),
                }
                samples[root]["body_head"] = body[:400]
        targeted_loop_elapsed = time.monotonic() - targeted_loop_t0

        # 空 targeted / 纯根细节：记录真实空包字节与根级 help 对应行
        empty_detail = {}
        for root in ("researchdump", "stop", "seed", "reload", "xp"):
            if root not in roots:
                continue
            rec = conn.exchange(f"help {root}", next(ids), next(ids), a_wait=1.5, b_wait=8.0)
            line = ""
            for ln in (first.get("body") or "").split("\n"):
                s = ln.strip()
                if s == "/" + root or s.startswith("/" + root + " "):
                    line = s
                    break
            empty_detail[root] = {
                "ok": rec.get("ok"), "a_packets": rec.get("a_packets"),
                "a_bytes": rec.get("a_bytes"), "a_chars": rec.get("a_chars"),
                "a_empty": rec.get("a_empty"),
                "b_text_ignored": rec.get("b_text_ignored"),
                "root_help_line": line,
            }
        ev["phases"]["empty_targeted_detail"] = empty_detail

        # 末次根 help + 尾随窗口
        final = conn.exchange("help", next(ids), next(ids), a_wait=3.0, b_wait=15.0,
                              trailing=max(args.trailing, 5.0))
        ev["phases"]["final_help"] = {k: final[k] for k in final if k not in ("body", "chunks")}
        final_roots_nl, _ = split_roots(final.get("body", ""))
        ev["root_set_consistent"] = (set(final_roots_nl) == set(roots))
        ev["root_set_diff"] = sorted(set(final_roots_nl) ^ set(roots))[:20]
        scan_wall_elapsed = time.monotonic() - scan_wall_t0

        ev["phases"]["scan"] = {
            "scanned_roots": len(targets),
            "actual_requests": 2 * (len(targets) + 2),
            "targeted_loop_seconds": round(targeted_loop_elapsed, 2),
            "wall_clock_seconds": round(scan_wall_elapsed, 2),
            "wall_clock_scope": "initial root help + targeted loop + empty-detail + final root help + final trailing",
            "empty_packet_root_count": len(empty_roots),
            "empty_packet_roots": empty_roots[:20],
            "no_packet_root_count": len(used_no_packet),
            "no_packet_roots": used_no_packet[:20],
            "redirect_roots": redirect_roots[:20],
            "samples": samples,
        }
    finally:
        conn.close()

    # 能力探针：独立连接，不属于正式扫描
    caps = {}
    conn = RawRcon(host, port, password)
    conn.connect()
    try:
        for cmd in ("help help", "help 1", "help probe_no_such_cmd_%06x" % random.randint(0, 0xFFFFFF)):
            rec = conn.exchange(cmd, next(ids), next(ids), a_wait=1.5, b_wait=8.0)
            caps[cmd] = {
                "ok": rec.get("ok"),
                "a_chars": rec.get("a_chars", 0),
                "b_text_ignored": rec.get("b_text_ignored"),
                "error": rec.get("error"),
                "no_a_packet": rec.get("no_a_packet", False),
            }
            caps[cmd]["body_head"] = (rec.get("body") or "")[:300]
        ev["phases"]["capability"] = caps
    finally:
        conn.close()

    # 3. 扫描 socket 关闭后的普通命令隔离
    iso = RawRcon(host, port, password)
    iso.connect()
    iso.t_start = time.monotonic()
    iso.buf = b""
    iso.sock.sendall(frame(600001, TYPE_EXEC, "list"))
    iso_text = ""
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        pkts = iso._pump(deadline)
        if pkts:
            iso_text = "".join(p["text"] for p in pkts)
            break
    iso.close()
    ev["phases"]["post_scan_isolation"] = {
        "list_reply_head": iso_text[:200],
        "looks_like_list": ("players online" in iso_text.lower()
                            or "there are" in iso_text.lower()),
    }

    # 4. 双客户端只读竞争（记录故障形态，不作为并发安全证明）
    ev["phases"]["concurrent_clients"] = concurrent_clients(
        host, port, password,
        full_help_chars=ev["phases"]["initial_help"].get("a_chars"),
    )

    # 5. 插件侧：单包截断 + 共享锁
    full_chars = ev["phases"]["initial_help"].get("a_chars")
    ev["phases"]["plugin"] = asyncio.run(plugin_checks(host, port, password, full_chars))

    with io.open(args.out, "w", encoding="utf-8") as fh:
        json.dump(ev, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in ev.items() if k != "phases"}, ensure_ascii=False))
    print("phases:", list(ev["phases"]))
    print("wrote", args.out)


if __name__ == "__main__":
    main()

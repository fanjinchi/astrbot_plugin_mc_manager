"""运行时 dump 一键化：部署 KubeJS 脚本 → RCON 触发 → 解析命令反馈 → 重建知识库。

完成判定用「命令反馈」而不是标记文件：Minecraft 的 RCON 会阻塞到命令执行结束，并把
RconConsoleSource 的命令反馈随响应一起回传（证据见 tasks/archive/2026-10/
10-23-runtime-dump-oneclick/research/01-rcon-trigger.md §1）。因此「触发」与「完成判定」是同一次 RCON 调用。
"""

import asyncio
import json
import os

try:
    from astrbot.api import logger
except ImportError:  # 允许脱离 AstrBot 环境独立测试/复现（脚本直跑）
    import logging

    logger = logging.getLogger("mc_manager.runtime_dump")

DUMP_COMMAND = "researchdump"
SCRIPT_REL_PATH = os.path.join("kubejs", "server_scripts", "runtime_dump.js")
DONE_PREFIX = "[rd] DONE "
FAIL_PREFIX = "[rd] FAIL"

# 全量 dump 在复制服实测 0.3s / 6MB；180s 只是卡死/崩溃的兜底，不是预期耗时
TRIGGER_TIMEOUT = 180.0
RELOAD_TIMEOUT = 120.0
# /reload 后命令表重建通常 5s 内完成（实测 ~5s），30s 窗口足够；超时说明脚本本身报错
UNKNOWN_RETRY_INTERVAL = 2.0
UNKNOWN_RETRY_TIMES = 15

MANUAL_FALLBACK = (
    "手工四步：\n"
    "1) mkdir -p <服务器目录>/runtime_dump\n"
    "2) 把插件 assets/runtime_dump.js 复制到 <服务器目录>/kubejs/server_scripts/，重启或 /reload\n"
    "3) 游戏内 OP 或控制台执行 /researchdump\n"
    "4) /mc_kb_rebuild"
)

_ASSET_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "runtime_dump.js")


# ------------------------------------------------------------------ 纯函数（便于单测）


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_dump_summary(response: str):
    """从命令反馈里取 [rd] DONE 后的统计 JSON；拿不到合法统计返回 None。"""
    if not isinstance(response, str):
        return None
    idx = response.find(DONE_PREFIX)
    if idx < 0:
        return None
    payload = response[idx + len(DONE_PREFIX):].strip()
    if not payload:
        return None
    payload = payload.splitlines()[0].strip()
    try:
        data = json.loads(payload)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("counts"), dict):
        data["counts"] = {}
    if not isinstance(data.get("failed"), list):
        data["failed"] = []
    return data


def _response_says_unknown(response: str) -> bool:
    """命令还没注册时服务端返回 Unknown command —— 这一次并没有执行 dump。"""
    return isinstance(response, str) and "unknown" in response.lower()


def _rcon_error_kind(response: str) -> str:
    """识别 execute_async 的错误返回：disconnected / timeout / other / 空串（正常响应）。"""
    if not isinstance(response, str) or not response.startswith("错误:"):
        return ""
    if "命令响应超时" in response:
        return "timeout"
    if "无法连接到服务器" in response:
        return "disconnected"
    return "other"  # 鉴权失败/协议异常等：命令没有执行，不能当正常响应去等 DONE


def _script_deploy_needed(target: str, content: str) -> bool:
    """目标脚本缺失或内容与插件自带不一致时才需要部署（避免每次 reload）。"""
    try:
        with open(target, encoding="utf-8", errors="replace") as fh:
            return fh.read() != content
    except OSError:
        return True


def _format_counts(summary: dict) -> str:
    counts = summary.get("counts") or {}
    parts = ["%s %d" % (kind, _as_int(counts.get(kind)))
             for kind in ("item", "block", "entity", "fluid") if kind in counts]
    total = sum(_as_int(v) for v in counts.values())
    tail = "共 %d 条" % total
    duration = summary.get("duration_ms")
    if isinstance(duration, (int, float)):
        tail += ("，%.1fs" % (duration / 1000.0)) if duration >= 1000 else ("，%dms" % duration)
    return "%s（%s）" % (" / ".join(parts), tail)


def _fail_reason(response: str) -> str:
    idx = response.find(FAIL_PREFIX)
    if idx < 0:
        return "未知原因"
    rest = response[idx + len(FAIL_PREFIX):].strip()
    lines = rest.splitlines()
    return lines[0].strip() if lines else "未知原因"


def _read_asset_script() -> str:
    with open(_ASSET_SCRIPT, encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------------ 编排


class RuntimeDumpRunner:
    """一次「部署脚本 → 触发 → 解析反馈 → 重建」的编排。

    单飞锁由调用方（main.py）持有，本类不关心并发。
    """

    def __init__(self, server_dir: str, rcon):
        self.server_dir = (server_dir or "").strip()
        self.rcon = rcon

    async def run(self, rebuild) -> str:
        """执行全流程并返回中文回执；rebuild 是无参可调用对象（内部走 to_thread）。"""
        precheck = self._precheck()
        if precheck:
            return precheck

        dump_dir = os.path.join(self.server_dir, "runtime_dump")
        try:
            # JsonIO.write 不建父目录：目录必须先存在，否则 JS 侧四类全部写失败
            os.makedirs(dump_dir, exist_ok=True)
        except OSError as e:
            return "❌ 创建 runtime_dump 目录失败：%s\n请手工执行：mkdir -p %s" % (e, dump_dir)

        try:
            script = _read_asset_script()
        except OSError as e:
            return "❌ 读取插件自带脚本 assets/runtime_dump.js 失败：%s" % e

        target = os.path.join(self.server_dir, SCRIPT_REL_PATH)
        deployed = False
        if _script_deploy_needed(target, script):
            error = self._deploy(target, script)
            if error:
                return error
            deployed = True
            logger.info("运行时 dump 脚本已部署: %s", target)
            reload_resp = await self.rcon.execute_async("reload", timeout=RELOAD_TIMEOUT)
            kind = _rcon_error_kind(reload_resp)
            if kind == "disconnected":
                return ("❌ 脚本已写入，但 RCON 连不上，没能 /reload。\n"
                        "请在服务器里手工执行 /reload 后重试，或按下面流程手工完成：\n" + MANUAL_FALLBACK)
            if kind == "timeout":
                return "❌ /reload 未在 %ds 内返回，请查看服务器日志后重试" % int(RELOAD_TIMEOUT)
            if kind == "other":
                return ("❌ 脚本已写入，但 /reload 执行失败：%s\n"
                        "请在服务器里手工执行 /reload 后重试，或按下面流程手工完成：\n"
                        % reload_resp + MANUAL_FALLBACK)

        response, attempts, error = await self._trigger()
        if response is None:
            return error

        summary = _parse_dump_summary(response)
        if summary is None:
            if FAIL_PREFIX in response:
                return ("❌ 运行时 dump 失败：%s\n详情见服务器日志 logs/kubejs/server.log"
                        % _fail_reason(response))
            return ("❌ 命令已执行，但没收到 [rd] DONE 反馈，无法确认 dump 是否完成。\n"
                    "请查看 logs/kubejs/server.log 是否报错；确认 runtime_dump/*.json 已生成后"
                    "可执行 /mc_kb_rebuild 单独重建")

        try:
            rebuild_text = await asyncio.to_thread(rebuild)
        except Exception as exc:  # 重建异常不能拖垮插件，堆栈进日志
            logger.exception("运行时 dump 后重建知识库异常")
            return "⚠️ 运行时 dump 完成（%s），但重建知识库异常：%s" % (_format_counts(summary), exc)

        lines = ["✅ 运行时 dump 完成：" + _format_counts(summary)]
        failed = summary.get("failed") or []
        if failed:
            lines.append("⚠️ 导出失败的类别：%s（详见服务器日志）" % "、".join(str(k) for k in failed))
        if deployed:
            lines.append("· 已部署脚本到 kubejs/server_scripts/ 并 /reload")
        if attempts > 1:
            lines.append("· /reload 后第 %d 次触发才成功（命令注册延迟）" % attempts)
        lines.append(rebuild_text)
        return "\n".join(lines)

    def _precheck(self) -> str:
        if not self.server_dir:
            return "❌ 未配置 mc_server_dir（MC 服务器根目录），无法导出运行时 dump"
        if not os.path.isdir(self.server_dir):
            return "❌ mc_server_dir 不存在或不是目录：%s" % self.server_dir
        if not os.path.isdir(os.path.join(self.server_dir, "kubejs")):
            return "❌ 服务器目录下没有 kubejs/（未安装 KubeJS），无法自动导出。\n" + MANUAL_FALLBACK
        return ""

    def _deploy(self, target: str, script: str) -> str:
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(script)
        except OSError as e:
            return "❌ 写入脚本失败：%s\n请检查插件进程对 %s 的写权限" % (e, target)
        return ""

    async def _trigger(self):
        """触发 dump，返回 (响应文本, 尝试次数, "") 或 (None, 0, 失败回执)。"""
        for attempt in range(1, UNKNOWN_RETRY_TIMES + 2):
            response = await self.rcon.execute_async(DUMP_COMMAND, timeout=TRIGGER_TIMEOUT)
            kind = _rcon_error_kind(response)
            if kind == "disconnected":
                return None, 0, "❌ 无法连接服务器 RCON：%s\n" % response + MANUAL_FALLBACK
            if kind == "timeout":
                return None, 0, ("❌ %ds 内没等到 dump 结束（可能卡在 watchdog 或服务器过载）。\n"
                                 "请查看服务器日志确认是否仍在执行，不要重复触发。" % int(TRIGGER_TIMEOUT))
            if kind == "other":
                return None, 0, "❌ RCON 执行失败：%s\n请检查 RCON 密码/服务器状态后重试" % response
            if DONE_PREFIX in response or FAIL_PREFIX in response:
                return response, attempt, ""
            if not _response_says_unknown(response):
                # 首次没有 DONE/FAIL：可能刚 reload 完仍命中旧命令表（v1 脚本只写日志、无反馈），
                # 或反馈丢失。再触发一次（dump 幂等、亚秒级），第二次仍没有就如实回执。
                if attempt == 1:
                    logger.info("首次触发未收到 [rd] DONE 标记，%.0fs 后重试一次",
                                UNKNOWN_RETRY_INTERVAL)
                    await asyncio.sleep(UNKNOWN_RETRY_INTERVAL)
                    continue
                return response, attempt, ""
            if attempt > UNKNOWN_RETRY_TIMES:
                return None, 0, ("❌ /reload 后等待 %ds，服务器仍不认识 /%s 命令。\n"
                                 "可手工执行 /reload 后再试；仍不行请按下面流程手工完成：\n"
                                 % (int(UNKNOWN_RETRY_INTERVAL * UNKNOWN_RETRY_TIMES), DUMP_COMMAND)
                                 + MANUAL_FALLBACK)
            logger.info("命令尚未注册（第 %d 次），%.0fs 后重试", attempt, UNKNOWN_RETRY_INTERVAL)
            await asyncio.sleep(UNKNOWN_RETRY_INTERVAL)
        return None, 0, "❌ 触发失败：未得到服务器响应"

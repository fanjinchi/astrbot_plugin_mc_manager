"""
MC 服务器日志监听器
直接轮询同机 MC 服务端的 logs/latest.log，解析玩家聊天与系统事件。
替代旧的 log_server.py + log_client.py TCP 通道（要求 AstrBot 与 MC 服务端同机，
日志路径由 mc_server_dir 配置推出，无需任何额外部署）。

防护要点（借鉴同目录兄弟插件 Scintilla 的 log_watcher 经验，按需裁剪）：
- 轮询而非 inotify：Windows 兼容，且服务器重启重建文件时天然可感知
- 启动从文件尾起步，不回放历史消息
- 日志轮转/服务器重启三判据：文件变短 / inode 变化 / 文件头 256B 指纹变化
- 文件缺失（服务器未启动）视为正常状态，静默等待不报错
- 阻塞文件 IO 走 daemon 单线程执行器，卡死（如 NFS 挂载失效）不会拖住 AstrBot 事件循环
- 任务代际防护：stop 之后旧代际任务即使漏吞 CancelledError 也不会复活
"""

import asyncio
import os
import queue
import re
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Callable, Optional

from astrbot.api import logger


class _DaemonExecutor:
    """单线程 daemon 执行器：隔离阻塞文件 IO。

    刻意不用 ThreadPoolExecutor——它的线程不是 daemon，IO 卡死时会拖住进程退出。
    """

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._loop, name="mc-log-watcher-io", daemon=True
        )
        self._thread.start()

    def _loop(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            fn, fut = item
            if fut.set_running_or_notify_cancel():
                try:
                    fut.set_result(fn())
                except BaseException as e:
                    fut.set_exception(e)

    async def run(self, fn, timeout: float):
        """在线程中执行 fn，超时抛 asyncio.TimeoutError（线程本身遗留但无害）"""
        fut = Future()
        self._queue.put((fn, fut))
        return await asyncio.wait_for(asyncio.wrap_future(fut), timeout)

    def shutdown(self):
        self._queue.put(None)


class LogWatcher:
    """latest.log 轮询监听器（类 + set_*_callback 注入，与项目基础设施风格一致）"""

    # Minecraft 聊天日志的正则（沿用旧 log_client.py 的解析行为，不退步）
    CHAT_PATTERN = re.compile(r"<(?P<player>[^>]+)>\s+(?P<message>.*)")
    JOIN_PATTERN = re.compile(r"\[Server thread/INFO\]: (\S+) joined the game$")
    LEAVE_PATTERN = re.compile(r"\[Server thread/INFO\]: (\S+) left the game$")
    ADVANCEMENT_PATTERN = re.compile(
        r"\[Server thread/INFO\]: (\S+) has made the advancement \[(.+)\]$"
    )

    # 死亡事件关键词（英文原版日志句式；中文服务端/非标准核心不在支持范围）
    DEATH_KEYWORDS = [
        "was slain by", "was shot by", "fell from", "drowned",
        "suffocated in", "tried to swim in", "was blown up by",
        "hit the ground", "withered away", "went up in flames",
        "burned to death", "was killed", "was pummeled by",
        "starved to death", "was pricked to death", "was impaled",
        "experienced kinetic energy", "blew up", "was squashed",
        "fell out of", "died",
    ]

    POLL_INTERVAL = 1.0          # 轮询间隔（秒）
    IO_TIMEOUT = 15.0            # 单次文件 IO 超时（秒）
    MAX_READ_BYTES = 1 * 1024 * 1024    # 每轮最多读 1MiB
    BACKLOG_JUMP_BYTES = 8 * 1024 * 1024  # 积压超过 8MiB 直接跳到文件尾
    FINGERPRINT_BYTES = 256      # 文件头指纹长度

    def __init__(self, log_file_path: str):
        """
        初始化日志监听器

        Args:
            log_file_path: latest.log 的完整路径（通常由 mc_server_dir/logs/latest.log 推出）
        """
        self.log_file_path = Path(log_file_path)
        self.on_chat: Optional[Callable] = None              # async (player, message)
        self.on_player_join: Optional[Callable] = None       # async (player)
        self.on_player_leave: Optional[Callable] = None      # async (player)
        self.on_player_advancement: Optional[Callable] = None  # async (player, advancement)
        self.on_player_death: Optional[Callable] = None      # async (player, reason)

        self._executor: Optional[_DaemonExecutor] = None
        self._task: Optional[asyncio.Task] = None
        self._gen = 0  # 任务代际：stop 时 +1，旧任务发现代际不符立即退出

        # 健康度状态（供 test_log 指令展示）
        self._pos: Optional[int] = None
        self._encoding: Optional[str] = None
        self._missing_polls = 0

    # ---------- 生命周期 ----------

    async def start(self):
        """启动监听（幂等；重复调用不会起第二个任务）"""
        if self._task is not None and not self._task.done():
            return
        if self._executor is None:
            self._executor = _DaemonExecutor()
        self._gen += 1
        self._task = asyncio.create_task(self._run(self._gen))
        logger.info(f"[MC日志] 监听已启动: {self.log_file_path}")

    async def stop(self):
        """停止监听并清理资源"""
        self._gen += 1
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"[MC日志] 停止监听任务时出现异常: {e}")
        if self._executor is not None:
            self._executor.shutdown()
            self._executor = None
        logger.info("[MC日志] 监听已停止")

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status_text(self) -> str:
        """健康度摘要（给 test_log 指令）"""
        exists = self.log_file_path.exists()
        lines = [
            f"日志文件: {self.log_file_path}",
            f"文件存在: {'是' if exists else '否（服务器可能未启动）'}",
            f"监听状态: {'运行中' if self.running else '已停止'}",
            f"读取位置: {self._pos if self._pos is not None else '未定位（等待文件出现）'}",
            f"日志编码: {self._encoding or '未探测'}",
            f"文件缺失轮数: {self._missing_polls}",
        ]
        return "\n".join(lines)

    # ---------- 回调注入 ----------

    def set_chat_callback(self, callback: Callable):
        """设置聊天回调：async def cb(player: str, message: str)"""
        self.on_chat = callback

    def set_player_join_callback(self, callback: Callable):
        """设置登入回调：async def cb(player: str)"""
        self.on_player_join = callback

    def set_player_leave_callback(self, callback: Callable):
        """设置登出回调：async def cb(player: str)"""
        self.on_player_leave = callback

    def set_player_advancement_callback(self, callback: Callable):
        """设置成就回调：async def cb(player: str, advancement: str)"""
        self.on_player_advancement = callback

    def set_player_death_callback(self, callback: Callable):
        """设置死亡回调：async def cb(player: str, reason: str)"""
        self.on_player_death = callback

    def _dispatch(self, callback: Optional[Callable], *args):
        """调度回调到事件循环；回调内部自行吞异常（项目约定：异常不得穿透管线）"""
        if callback is None:
            return
        try:
            asyncio.create_task(callback(*args))
        except Exception as e:
            logger.error(f"[MC日志] 调度事件回调失败: {e}")

    # ---------- 阻塞 IO（全部走 daemon 执行器） ----------

    def _stat_sync(self):
        try:
            return os.stat(self.log_file_path)
        except OSError:
            return None

    def _fingerprint_sync(self) -> Optional[bytes]:
        try:
            with open(self.log_file_path, "rb") as f:
                return f.read(self.FINGERPRINT_BYTES)
        except OSError:
            return None

    def _read_sync(self, offset: int, length: int) -> bytes:
        with open(self.log_file_path, "rb") as f:
            f.seek(offset)
            return f.read(length)

    # ---------- 主循环 ----------

    async def _run(self, gen: int):
        pos: Optional[int] = None
        inode: Optional[int] = None
        fingerprint: Optional[bytes] = None
        pending = b""  # 半行缓冲：日志行未以换行结尾时留到下一轮拼接
        encoding: Optional[str] = None
        first_positioning = True  # 仅插件启动后的首次定位从文件尾起步
        self._pos = None
        self._missing_polls = 0

        while gen == self._gen:
            try:
                st = await self._executor.run(self._stat_sync, self.IO_TIMEOUT)

                # 文件不存在：服务器未启动或轮转窗口，静默等待
                if st is None:
                    if pos is not None:
                        logger.info("[MC日志] 日志文件消失（服务器停止或轮转中），等待重新出现")
                    pos = None
                    inode = None
                    fingerprint = None
                    encoding = None
                    pending = b""
                    self._pos = None
                    self._encoding = None
                    self._missing_polls += 1
                    await asyncio.sleep(self.POLL_INTERVAL)
                    continue
                self._missing_polls = 0

                # 定位：插件启动的首次定位从文件尾起步（不回放历史）；
                # 文件消失后重建（服务器重启）则从头读——新文件的内容全是新事件
                if pos is None:
                    pos = st.st_size if first_positioning else 0
                    first_positioning = False
                    inode = st.st_ino
                    fingerprint = await self._executor.run(
                        self._fingerprint_sync, self.IO_TIMEOUT
                    )
                    if pos > 0:
                        logger.info(
                            f"[MC日志] 已定位到文件尾（{st.st_size} 字节），开始监听新日志"
                        )
                    else:
                        logger.info("[MC日志] 日志文件重建，从头读取新日志")
                    continue

                # 轮转/重启检测：变短、inode 变化、文件头指纹变化（三判据）
                rotated = st.st_size < pos or st.st_ino != inode
                if not rotated:
                    new_fp = await self._executor.run(
                        self._fingerprint_sync, self.IO_TIMEOUT
                    )
                    if new_fp is not None and fingerprint is not None:
                        if len(new_fp) != len(fingerprint):
                            # 指纹长度变化说明文件在增长（小文件从不足 256B 长到超过），
                            # 不可比对；趁势刷新指纹基准，避免长成 256B 时误判轮转
                            if len(new_fp) > len(fingerprint):
                                fingerprint = new_fp
                        elif new_fp != fingerprint:
                            rotated = True
                if rotated:
                    logger.info("[MC日志] 检测到日志轮转/服务器重启，从头读取新日志")
                    pos = 0
                    inode = st.st_ino
                    fingerprint = await self._executor.run(
                        self._fingerprint_sync, self.IO_TIMEOUT
                    )
                    pending = b""
                    encoding = None

                # 积压过多（如插件卡了很久）：直接追尾，避免回放刷屏
                if st.st_size - pos > self.BACKLOG_JUMP_BYTES:
                    logger.warning(
                        f"[MC日志] 日志积压超过 {self.BACKLOG_JUMP_BYTES} 字节，跳到文件尾"
                    )
                    pos = st.st_size
                    pending = b""
                elif st.st_size > pos:
                    length = min(st.st_size - pos, self.MAX_READ_BYTES)
                    data = await self._executor.run(
                        lambda: self._read_sync(pos, length), self.IO_TIMEOUT
                    )
                    pos += len(data)
                    pending += data
                    lines, pending = self._split_lines(pending)
                    if lines and encoding is None:
                        encoding = self._sniff_encoding(lines)
                        self._encoding = encoding
                    for raw in lines:
                        line = raw.decode(encoding or "utf-8", errors="replace").rstrip(
                            "\r"
                        )
                        if line:
                            self._process_log_line(line)

                self._pos = pos
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[MC日志] 监听循环异常: {e}")

            await asyncio.sleep(self.POLL_INTERVAL)

    @staticmethod
    def _split_lines(data: bytes) -> tuple[list[bytes], bytes]:
        """把字节流切成完整行，残留半行返回给下一轮"""
        lines = data.split(b"\n")
        return lines[:-1], lines[-1]

    @staticmethod
    def _sniff_encoding(lines: list[bytes]) -> str:
        """编码嗅探：UTF-8 严格解码通过则用 UTF-8，否则按 GBK 处理（Windows 中文服务端）"""
        sample = b"\n".join(lines[:20])
        try:
            sample.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            return "gbk"

    # ---------- 日志行解析（沿用旧 log_client.py 的行为与顺序） ----------

    def _process_log_line(self, log_line: str):
        # 1. 玩家登入
        match = self.JOIN_PATTERN.search(log_line)
        if match:
            player = match.group(1)
            logger.info(f"[MC事件] {player} 加入了游戏")
            self._dispatch(self.on_player_join, player)
            return

        # 2. 玩家登出
        match = self.LEAVE_PATTERN.search(log_line)
        if match:
            player = match.group(1)
            logger.info(f"[MC事件] {player} 离开了游戏")
            self._dispatch(self.on_player_leave, player)
            return

        # 3. 达成成就
        match = self.ADVANCEMENT_PATTERN.search(log_line)
        if match:
            player, advancement = match.group(1), match.group(2)
            logger.info(f"[MC事件] {player} 达成了成就 [{advancement}]")
            self._dispatch(self.on_player_advancement, player, advancement)
            return

        # 4. 死亡事件
        death = self._parse_death_event(log_line)
        if death:
            player, reason = death
            logger.info(f"[MC事件] {player} 死亡: {reason}")
            self._dispatch(self.on_player_death, player, reason)
            return

        # 5. 玩家聊天（最宽松的匹配放最后）
        match = self.CHAT_PATTERN.search(log_line)
        if match:
            player = match.group("player")
            message = match.group("message")
            logger.info(f"[MC聊天] <{player}> {message}")
            self._dispatch(self.on_chat, player, message)

    def _parse_death_event(self, log_line: str) -> Optional[tuple[str, str]]:
        """解析死亡事件，返回 (玩家名, 死因描述) 或 None"""
        if "[Server thread/INFO]:" not in log_line:
            return None
        try:
            content = log_line.split("[Server thread/INFO]: ")[1].strip()
            # 排除玩家聊天与其他系统行
            if content.startswith("<"):
                return None
            if any(
                kw in content
                for kw in ("logged in", "lost connection", "joined the game", "left the game")
            ):
                return None
            for keyword in self.DEATH_KEYWORDS:
                if keyword in content:
                    parts = content.split(" ")
                    if parts:
                        return parts[0], content
            return None
        except Exception:
            return None

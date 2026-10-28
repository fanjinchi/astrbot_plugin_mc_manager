"""
Minecraft RCON客户端封装
支持Fabric、Forge、NeoForge等所有使用标准RCON协议的服务器
使用异步长连接方式
"""

import asyncio
import struct
from aiomcrcon import Client
from aiomcrcon.errors import ClientNotConnectedError, RCONConnectionError
from typing import Optional
from astrbot.api import logger

try:  # 以插件包导入（生产）
    from .rcon_help import ScanLimits, scan_help
except ImportError:  # 以顶层模块导入（tests/ 直接把插件目录放进 sys.path）
    from rcon_help import ScanLimits, scan_help


# 值得断开重连后重试的异常：aiomcrcon 的连接错误不是 OSError 子类，必须显式列出；
# struct.error 是连接已断时读到空包的表现（停服/重启后首条命令）。
TRANSIENT_RCON_ERRORS = (
    ConnectionRefusedError,
    ConnectionResetError,
    BrokenPipeError,
    OSError,
    RCONConnectionError,
    ClientNotConnectedError,
    struct.error,
)


class MinecraftRCON:
    """Minecraft RCON客户端封装类（异步长连接）"""
    
    def __init__(self, host: str, port: int, password: str):
        """
        初始化RCON客户端
        
        Args:
            host: MC服务器地址
            port: RCON端口（默认25575）
            password: RCON密码
        """
        self.host = host
        self.port = port
        self.password = password
        self._client: Optional[Client] = None
        self._lock = asyncio.Lock()
        # 命令发送锁：同一 socket 上并发 send_cmd 会让响应串包（长命令执行期间其它调用排队）
        self._send_lock = asyncio.Lock()
    
    async def _ensure_connection(self) -> Client:
        """确保RCON连接存在且有效"""
        async with self._lock:
            if self._client is None:
                try:
                    self._client = Client(self.host, self.port, self.password)
                    await self._client.connect()
                    logger.info(f"RCON连接已建立: {self.host}:{self.port}")
                except Exception as e:
                    logger.error(f"RCON连接建立失败: {e}")
                    self._client = None
                    raise
            return self._client
    
    async def _reconnect(self):
        """重新建立连接"""
        async with self._lock:
            if self._client:
                try:
                    await self._client.close()
                except:
                    pass
                self._client = None
    
    async def execute_async(self, command: str, timeout: Optional[float] = None) -> str:
        """
        执行RCON命令
        
        Args:
            command: 要执行的MC命令（不需要/前缀）
            timeout: 等待响应的秒数；None 用 aiomcrcon 默认的 2s。
                     执行时长远超 2s 的命令（如 KubeJS dump）必须显式放大，否则会被判超时。
            
        Returns:
            命令执行结果
        """
        # 移除可能的/前缀
        if command.startswith('/'):
            command = command[1:]
        
        max_retries = 2
        for attempt in range(max_retries):
            sent = False
            try:
                client = await self._ensure_connection()
                async with self._send_lock:
                    sent = True
                    if timeout is None:
                        response = await client.send_cmd(command)
                    else:
                        response = await client.send_cmd(command, timeout=timeout)
                # aiomcrcon 的 send_cmd 返回 (响应文本, 请求ID) 元组，只取文本
                # （旧代码直接把元组插进返回字符串，会产生 "('...', 5)" 这样的脏文本）
                if isinstance(response, tuple):
                    response = response[0]
                logger.info(f"执行命令: {command}, 响应: {response}")
                return response if response else "命令执行成功（无返回信息）"
            except asyncio.TimeoutError:
                if not sent:
                    # 登录阶段超时：TCP 连上了但 RCON 没在 2s 内回登录包，命令根本没发出去
                    logger.warning(f"RCON登录超时 (尝试 {attempt + 1}/{max_retries}): {self.host}:{self.port}")
                    await self._reconnect()
                    if attempt == max_retries - 1:
                        return "错误: RCON 登录超时（服务器未在 2s 内完成登录，命令未发送）"
                    continue
                # 超时 ≠ 命令没执行：服务器只是还没把响应写完。重连丢弃挂起的响应，但绝不重发，
                # 否则 dump 这类长命令会被执行两次（wait_for 抛 TimeoutError，3.11+ 它是 OSError
                # 子类，必须先于 TRANSIENT_RCON_ERRORS 捕获，否则会被当成连接异常重试）。
                limit = f"{timeout:g}s" if timeout is not None else "默认 2s"
                logger.warning(f"RCON命令响应超时（>{limit}）: {command}")
                await self._reconnect()
                return f"错误: 命令响应超时（>{limit}，命令可能已在服务器执行）"
            except TRANSIENT_RCON_ERRORS as e:
                logger.warning(f"RCON连接异常 (尝试 {attempt + 1}/{max_retries}): {e}")
                await self._reconnect()
                if attempt == max_retries - 1:
                    error_msg = f"无法连接到服务器 {self.host}:{self.port}，请检查服务器是否启动且RCON已启用"
                    logger.error(error_msg)
                    return f"错误: {error_msg}"
            except Exception as e:
                error_msg = f"执行命令时出错: {str(e)}"
                logger.error(error_msg)
                return f"错误: {error_msg}"
    
    async def test_connection_async(self) -> tuple[bool, str]:
        """
        测试RCON连接
        
        Returns:
            (是否成功, 消息)
        """
        try:
            client = await self._ensure_connection()
            async with self._send_lock:
                response = await client.send_cmd("list")
            if isinstance(response, tuple):
                response = response[0]
            return True, f"连接成功！{response}"
        except ConnectionRefusedError:
            return False, f"无法连接到 {self.host}:{self.port}"
        except Exception as e:
            return False, f"连接失败: {str(e)}"
    
    async def scan_help_commands(
        self, limits: ScanLimits | None = None
    ) -> tuple[dict | None, dict]:
        """用独立扫描 socket 采集 RCON help 命令树（整次扫描持有 _send_lock）。

        服务端不同 RCON socket 共享同一反馈缓冲，所以扫描必须与普通命令走同一个
        互斥边界；锁覆盖整次扫描，普通命令在扫描结束前只会排队等待，不会在 A/B
        交换之间写入。返回 (snapshot | None, report)，失败只关闭扫描 socket，
        不改动现有普通连接。

        Args:
            limits: rcon_help.ScanLimits；None 用内部默认预算（不新增配置项）

        Returns:
            (未写盘的 rcon 快照或 None, 诊断报告)
        """
        async with self._send_lock:
            return await scan_help(self.host, self.port, self.password, limits)

    async def close(self):
        """关闭RCON连接"""
        async with self._lock:
            if self._client:
                try:
                    await self._client.close()
                    logger.info("RCON连接已关闭")
                except:
                    pass
                self._client = None
    
    def __del__(self):
        """析构时关闭连接"""
        if self._client:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.close())
                else:
                    loop.run_until_complete(self.close())
            except:
                pass
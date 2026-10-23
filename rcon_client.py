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
    
    async def execute_async(self, command: str) -> str:
        """
        执行RCON命令
        
        Args:
            command: 要执行的MC命令（不需要/前缀）
            
        Returns:
            命令执行结果
        """
        # 移除可能的/前缀
        if command.startswith('/'):
            command = command[1:]
        
        max_retries = 2
        for attempt in range(max_retries):
            try:
                client = await self._ensure_connection()
                response = await client.send_cmd(command)
                # aiomcrcon 的 send_cmd 返回 (响应文本, 请求ID) 元组，只取文本
                # （旧代码直接把元组插进返回字符串，会产生 "('...', 5)" 这样的脏文本）
                if isinstance(response, tuple):
                    response = response[0]
                logger.info(f"执行命令: {command}, 响应: {response}")
                return response if response else "命令执行成功（无返回信息）"
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
            response = await client.send_cmd("list")
            if isinstance(response, tuple):
                response = response[0]
            return True, f"连接成功！{response}"
        except ConnectionRefusedError:
            return False, f"无法连接到 {self.host}:{self.port}"
        except Exception as e:
            return False, f"连接失败: {str(e)}"
    
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
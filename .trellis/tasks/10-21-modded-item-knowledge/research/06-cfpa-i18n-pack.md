# CFPA 汉化包（I18nUpdateMod 数据源）调研纪要

调研时间：2026-10-21（子代理网络调研 + 主会话 mcmod.cn 复核）

## 结论

1. **I18nUpdateMod（现役为 I18nUpdateMod3）是纯客户端 mod**（fabric.mod.json 写明 "environment": "client"），服务端装它无效。它的作用只是帮客户端自动下载 CFPA 汉化资源包。→ 插件方案与该 mod 无关，直接拿资源包数据即可。
2. **补译数据可直接下载成品 zip，无需 clone 仓库**：
   - GitHub Releases：<https://github.com/CFPAOrg/Minecraft-Mod-Language-Package/releases>，tag 形如 Snapshot-20260917125024，资产命名 Minecraft-Mod-Language-Modpack-1-20.zip、...-1-21.zip、Minecraft-Mod-Language-Modpack.zip（1.12.2），附同名 .md5。
   - BMCLAPI 国内镜像（实测 HTTP 200）：<https://bmclapi2.bangbang93.com/mirrors/i18n-update-mod/>
3. **zip 内部即标准资源包结构**：pack.mcmeta + assets/<modid>/lang/zh_cn.json（1.13+）或 zh_cn.lang（1.12.2-）。Python zipfile+json 即可解析。1.21 包实测 388 个 zh_cn.json；1.12.2 包 1600 个 zh_cn.lang。
4. **key 形态**：1.13+ 为 item.<命名空间>.<路径>（无 .name 后缀）；1.12.2 为 item.<modid>.<name>.name（带 .name）。覆盖 item/block/entity/tag/advancements 等；fluid/tooltip 取决于模组命名。
5. **仓库目录多一级 slug**：projects/<version>/assets/<CurseForge slug>/<命名空间>/lang/zh_cn.json（clone 仓库时才需要关心；成品包已拍平成 assets/<modid>/lang/）。
6. **许可证 CC BY-NC-SA 4.0**（署名、非商业、相同方式共享）：插件运行时下载不随插件分发 + README/指令输出署名即可合规；不得把翻译库预打包进插件发布。mod 代码本身 AGPL-3.0-only，与数据许可分开。

## 落地要点

- 按服务器 MC 版本选包（1.20.1 → Minecraft-Mod-Language-Modpack-1-20.zip）；优先 GitHub Releases，失败回退 BMCLAPI 镜像；支持服主手动把 zip 放进插件数据目录兜底。
- 用同名 .md5 做更新检测；Snapshot 约每 1-2 周更新一次。
- 来源标注文案：「翻译数据来自 CFPA Minecraft-Mod-Language-Package，CC BY-NC-SA 4.0」。

## 参考链接

- mod 源码（现役）：<https://github.com/CFPAOrg/I18nUpdateMod3>
- 数据仓库：<https://github.com/CFPAOrg/Minecraft-Mod-Language-Package>
- 打包机制文档：<https://github.com/CFPAOrg/Minecraft-Mod-Language-Package/blob/main/Packer-Doc.md>
- MC百科条目：<https://www.mcmod.cn/class/1188.html>
- 官网手动下载页：<https://cfpa.site/>

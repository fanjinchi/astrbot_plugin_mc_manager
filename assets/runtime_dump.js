// 物品知识库运行时 dump 脚本（KubeJS；Minecraft 1.19.2 实测，1.20.1+ 兼容）
//
// 用法（手工四步；插件 /mc_kb_dump 会自动完成前两步并触发第 3 步）：
//   1) mkdir -p <mc_server_dir>/runtime_dump      —— KubeJS 的 JsonIO 不会自动建父目录
//   2) 复制本文件到 <mc_server_dir>/kubejs/server_scripts/，然后重启服务器或执行 /reload
//   3) 游戏内 OP（权限等级 ≥2）或控制台执行 /researchdump
//      产物：<mc_server_dir>/runtime_dump/{item,block,entity,fluid}.json
//      命令结束后会回传一行 [rd] DONE {...} 统计（插件靠它判断完成，没有标记文件）
//   4) 执行 /mc_kb_rebuild 重建物品知识库（运行时注册表是权威数据）
//
// 说明：只导出注册表内容，不额外打日志；全量约 2.7 万条 / 0.3s / 6MB（复制服实测）。

const RD_VERSION = '2'

function rdRegistry() {
  try {
    return Java.loadClass('net.minecraft.core.registries.BuiltInRegistries')
  } catch (e) {
    // 1.19.2 没有 BuiltInRegistries，退回 Registry；成员名靠 Rhino 的 Mojmap 重映射
    console.info('[rd] 未找到 BuiltInRegistries，退回 Registry 访问')
    return Java.loadClass('net.minecraft.core.Registry')
  }
}

function rdComponent() {
  return Java.loadClass('net.minecraft.network.chat.Component')
}

function rdSnbt(stack) {
  return stack.save(new (Java.loadClass('net.minecraft.nbt.CompoundTag'))()).toString()
}

// spec = [kind, 注册表字段名, 是否导出 SNBT]
function rdOne(REG, Component, ItemStack, spec) {
  var kind = spec[0]
  var reg = REG[spec[1]]
  if (!reg) throw new Error('注册表字段不存在: ' + spec[1])
  var withStack = spec[2]
  var arr = reg.entrySet().toArray()
  var entries = []
  for (var i = 0; i < arr.length; i++) {
    var value = arr[i].getValue()
    var entry = { kind: kind, id: String(arr[i].getKey()), tkey: '', resolved: '' }
    try { entry.tkey = value.getDescriptionId() } catch (e) { entry.tkey = '' }
    try { entry.resolved = Component.translatable(entry.tkey).getString() } catch (e) { entry.resolved = '' }
    if (withStack) {
      try { entry.stack = rdSnbt(new ItemStack(value)) } catch (e) { entry.stack = '' }
    }
    entries.push(entry)
  }
  return entries
}

function rdDump() {
  var REG = rdRegistry()
  var Component = rdComponent()
  var ItemStack = Java.loadClass('net.minecraft.world.item.ItemStack')
  var started = Date.now()
  var counts = {}
  var failed = []
  var specs = [
    ['item', 'ITEM', true],
    ['block', 'BLOCK', false],
    ['entity', 'ENTITY_TYPE', false],
    ['fluid', 'FLUID', false]
  ]
  for (var s = 0; s < specs.length; s++) {
    var kind = specs[s][0]
    try {
      var entries = rdOne(REG, Component, ItemStack, specs[s])
      counts[kind] = entries.length
      if (entries.length > 0) {
        // 字符串路径直传：KubeJS 的 TypeWrapper 会解析成 Path 并做 verifyFilePath 校验
        JsonIO.write('runtime_dump/' + kind + '.json', {
          kind: kind,
          count: entries.length,
          entries: entries
        })
      }
      console.info('[rd] ' + kind + ' ' + entries.length)
    } catch (e) {
      failed.push(kind)
      console.warn('[rd] ' + kind + ' 导出失败: ' + e)
    }
  }
  return { version: RD_VERSION, duration_ms: Date.now() - started, counts: counts, failed: failed }
}

ServerEvents.commandRegistry(event => {
  event.register(event.commands.literal('researchdump')
    .requires(source => source.hasPermission(2))
    .executes(ctx => {
      var message
      try {
        message = '[rd] DONE ' + JSON.stringify(rdDump())
      } catch (e) {
        message = '[rd] FAIL ' + String(e)
      }
      // 命令反馈会随 RCON 响应一起回传，插件靠这一行判断完成（不写标记文件、不轮询）
      try { ctx.source.sendSystemMessage(rdComponent().literal(message)) } catch (e) {}
      return 1
    }))
})

// 物品知识库运行时 dump 脚本（KubeJS；Minecraft 1.19.2 实测，1.20.1 兼容）
//
// 用法（手工四步；插件 /mc_kb_dump 会自动完成前两步并触发第 3 步）：
//   1) mkdir -p <mc_server_dir>/runtime_dump      —— KubeJS 的 JsonIO 不会自动建父目录
//   2) 复制本文件到 <mc_server_dir>/kubejs/server_scripts/，然后重启服务器或执行 /reload
//   3) 游戏内 OP（权限等级 ≥2）或控制台执行 /researchdump
//      产物：<mc_server_dir>/runtime_dump/{item,block,entity,fluid,commands}.json
//      命令结束后会回传一行 [rd] DONE {...} 统计（插件靠它判断完成，没有标记文件）
//   4) 执行 /mc_kb_rebuild 重建知识库并导入命令快照（运行时注册表是权威数据）
//
// 说明：只导出注册表内容，不额外打日志；全量物品约 2.7 万条 / 0.3s / 6MB（复制服实测）。
// 命令树来自当前活动 dispatcher 的 getAllUsage；已注册路径不代表当前调用者必然可执行。

const RD_VERSION = '3'

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

// 命令树扁平 usage：dispatcher.getAllUsage 一次 DFS，restricted=false 不做 requires 可见性过滤。
// 输出形如 "foo" / "foo bar" / "foo <count>" / "alias -> foo" / "loop ..."（1.0.18 与 1.1.8 实测一致）。
function rdCommandEntries(ctx) {
  var dispatcher = ctx.source.getServer().getCommands().getDispatcher()
  var usages = dispatcher.getAllUsage(dispatcher.getRoot(), ctx.source, false)
  var entries = []
  for (var i = 0; i < usages.length; i++) {
    var line = String(usages[i]).trim()
    if (!line) continue
    var redirect = ''
    var syntax = line
    var arrow = line.indexOf(' -> ')
    if (arrow > 0) {
      redirect = line.substring(arrow + 4).trim()
      syntax = line.substring(0, arrow).trim()
    } else if (line.length > 3 && line.substring(line.length - 3) === ' ->') {
      // 目标是外部 dispatcher 的 root（usageText 为空）时 Brigadier 输出 "prefix ->"，
      // 不能用可执行语法呈现，按 redirect 标记处理
      redirect = '...'
      syntax = line.substring(0, line.length - 3).trim()
    } else if (line.length > 4 && line.substring(line.length - 4) === ' ...') {
      // redirect 到 root 时 Brigadier 输出 "prefix ..."，拆成 redirect 标记而不是可执行语法
      redirect = '...'
      syntax = line.substring(0, line.length - 4).trim()
    }
    var name = syntax.split(' ')[0]
    if (!name) continue
    var entry = { name: name, syntax: syntax, source: 'unknown', level: null }
    if (redirect) entry.redirect = redirect
    entries.push(entry)
  }
  return entries
}

function rdDump(ctx) {
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
  // 命令树与四类注册表相互独立：失败只影响 commands 类别，不写空文件、不覆盖旧快照
  try {
    var commandEntries = rdCommandEntries(ctx)
    if (commandEntries.length > 0) {
      JsonIO.write('runtime_dump/commands.json', {
        kind: 'commands',
        schema_version: 1,
        producer: 'kubejs',
        count: commandEntries.length,
        entries: commandEntries
      })
      counts.commands = commandEntries.length
      console.info('[rd] commands ' + commandEntries.length)
    } else {
      failed.push('commands')
      console.warn('[rd] commands 导出失败: 命令树为空')
    }
  } catch (e) {
    failed.push('commands')
    console.warn('[rd] commands 导出失败: ' + e)
  }
  return { version: RD_VERSION, duration_ms: Date.now() - started, counts: counts, failed: failed }
}

ServerEvents.commandRegistry(event => {
  event.register(event.commands.literal('researchdump')
    .requires(source => source.hasPermission(2))
    .executes(ctx => {
      var message
      try {
        message = '[rd] DONE ' + JSON.stringify(rdDump(ctx))
      } catch (e) {
        message = '[rd] FAIL ' + String(e)
      }
      // 命令反馈会随 RCON 响应一起回传，插件靠这一行判断完成（不写标记文件、不轮询）
      try { ctx.source.sendSystemMessage(rdComponent().literal(message)) } catch (e) {}
      return 1
    }))
})

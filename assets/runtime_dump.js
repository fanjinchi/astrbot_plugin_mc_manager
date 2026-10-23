// 物品知识库运行时 dump 增强脚本（KubeJS，Forge/NeoForge 1.20.1 实测）
// 用法：
//   1) 复制本文件到 <mc_server_dir>/kubejs/server_scripts/，重启或 /reload
//   2) 进服执行 /researchdump —— 结果以 "##RD##" 前缀写入服务器日志 logs/latest.log
//   3) 执行 python3 assets/extract_runtime_dump.py <mc_server_dir>/logs/latest.log <mc_server_dir>/runtime_dump
//   4) /mc_kb_rebuild 重建时会自动合并 runtime_dump/*.jsonl（运行时注册表是权威数据）
//
// 说明：脚本只导出物品/方块/实体/流体注册表，每次执行会把全量条目写进日志（几万行），
// 完成后建议 /reload 或重启去掉本脚本，避免以后日志里再出现 ##RD## 行。

function rdEmit(o) { console.info('##RD##' + JSON.stringify(o)) }

function rdSnbt(stack) {
  var t = Java.loadClass('net.minecraft.nbt.CompoundTag')
  try { return stack.save(new t()).toString() } catch (e) { return 'ERR' }
}

function rdItems() {
  var BIR = Java.loadClass('net.minecraft.core.registries.BuiltInRegistries')
  var IS = Java.loadClass('net.minecraft.world.item.ItemStack')
  var C = Java.loadClass('net.minecraft.network.chat.Component')
  var arr = BIR.ITEM.entrySet().toArray()
  for (var i = 0; i < arr.length; i++) {
    var it = arr[i].getValue()
    var tid = ''
    var res = ''
    var st = ''
    try { tid = it.getDescriptionId() } catch (e) {}
    try { res = C.translatable(tid).getString() } catch (e) {}
    try { st = rdSnbt(new IS(it)) } catch (e) {}
    rdEmit({ kind: 'item', id: String(arr[i].getKey()), tkey: tid, resolved: res, stack: st })
  }
  console.info('[rd] items ' + arr.length)
}

function rdBlocks() {
  var BIR = Java.loadClass('net.minecraft.core.registries.BuiltInRegistries')
  var C = Java.loadClass('net.minecraft.network.chat.Component')
  var arr = BIR.BLOCK.entrySet().toArray()
  for (var i = 0; i < arr.length; i++) {
    var b = arr[i].getValue()
    var tid = ''
    var res = ''
    try { tid = b.getDescriptionId() } catch (e) {}
    try { res = C.translatable(tid).getString() } catch (e) {}
    rdEmit({ kind: 'block', id: String(arr[i].getKey()), tkey: tid, resolved: res })
  }
  console.info('[rd] blocks ' + arr.length)
}

function rdEntities() {
  var BIR = Java.loadClass('net.minecraft.core.registries.BuiltInRegistries')
  var C = Java.loadClass('net.minecraft.network.chat.Component')
  var arr = BIR.ENTITY_TYPE.entrySet().toArray()
  for (var i = 0; i < arr.length; i++) {
    var et = arr[i].getValue()
    var tid = ''
    var res = ''
    try { tid = et.getDescriptionId() } catch (e) {}
    try { res = C.translatable(tid).getString() } catch (e) {}
    rdEmit({ kind: 'entity', id: String(arr[i].getKey()), tkey: tid, resolved: res })
  }
  console.info('[rd] entities ' + arr.length)
}

function rdFluids() {
  var BIR = Java.loadClass('net.minecraft.core.registries.BuiltInRegistries')
  var arr = BIR.FLUID.entrySet().toArray()
  for (var i = 0; i < arr.length; i++) rdEmit({ kind: 'fluid', id: String(arr[i].getKey()) })
  console.info('[rd] fluids ' + arr.length)
}

function rdAll(server) {
  console.info('[rd] start')
  try { rdItems() } catch (e) { console.info('[rd] items FAIL ' + e) }
  try { rdBlocks() } catch (e) { console.info('[rd] blocks FAIL ' + e) }
  try { rdEntities() } catch (e) { console.info('[rd] entities FAIL ' + e) }
  try { rdFluids() } catch (e) { console.info('[rd] fluids FAIL ' + e) }
  console.info('[rd] DONE')
}

ServerEvents.commandRegistry(event => {
  var Commands = event.commands
  event.register(Commands.literal('researchdump').executes(ctx => {
    try { rdAll(ctx.source.server) } catch (e) { console.info('[rd] FATAL ' + e) }
    return 1
  }))
})

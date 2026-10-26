// KubeJS 运行时桩：在不启动 Minecraft 服务端的情况下执行 assets/runtime_dump.js，
// 校验 RD_VERSION、commands.json 产物与 [rd] DONE 回执。由 tests/test_dump_script.py 驱动。
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SCRIPT = path.join(__dirname, "..", "assets", "runtime_dump.js");

function fakeRegistry(ids) {
  return {
    entrySet() {
      return {
        toArray() {
          return ids.map((id) => ({
            getKey: () => id,
            getValue: () => ({
              getDescriptionId: () => "item " + id,
              save: () => ({ toString: () => "{}" }),
            }),
          }));
        },
      };
    },
  };
}

function makeJava() {
  return {
    loadClass(name) {
      if (name === "net.minecraft.core.registries.BuiltInRegistries") {
        return {
          ITEM: fakeRegistry(["minecraft:stone", "minecraft:diamond"]),
          BLOCK: fakeRegistry(["minecraft:stone"]),
          ENTITY_TYPE: fakeRegistry(["minecraft:zombie"]),
          FLUID: fakeRegistry(["minecraft:water"]),
        };
      }
      if (name === "net.minecraft.world.item.ItemStack") {
        return function ItemStack() {};
      }
      if (name === "net.minecraft.nbt.CompoundTag") {
        return function CompoundTag() {};
      }
      if (name === "net.minecraft.network.chat.Component") {
        return {
          translatable: () => ({ getString: () => "" }),
          literal: (text) => ({ text }),
        };
      }
      throw new Error("未桩化的类: " + name);
    },
  };
}

function makeContext(usages, options) {
  const dispatcher = {
    getRoot: () => ({}),
    getAllUsage: () => {
      if (options.throwOnUsage) throw new Error("dispatcher 不可用");
      return usages;
    },
  };
  return {
    source: {
      hasPermission: () => 2,
      getServer: () => ({ getCommands: () => ({ getDispatcher: () => dispatcher }) }),
      sendSystemMessage: (component) => contextMessages.push(component.text),
    },
  };
}

const writes = [];
const contextMessages = [];
let handler = null;

function run({ usages, throwOnUsage }) {
  writes.length = 0;
  contextMessages.length = 0;
  handler = null;
  const sandbox = {
    console: { info() {}, warn() {} },
    Date,
    JSON,
    String,
    Java: makeJava(),
    JsonIO: { write: (target, payload) => writes.push({ path: target, payload }) },
    ServerEvents: {
      commandRegistry(register) {
        const node = {
          requires() {
            return node;
          },
          executes(fn) {
            handler = fn;
            return node;
          },
        };
        register({ register: () => node, commands: { literal: () => node } });
      },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SCRIPT, "utf8"), sandbox, { filename: "runtime_dump.js" });
  handler(makeContext(usages, { throwOnUsage }));
  return { writes: writes.slice(), messages: contextMessages.slice() };
}

const usages = ["foo", "foo bar", "foo <count>", "alias -> foo", "loop ..."];
const ok = run({ usages, throwOnUsage: false });
const broken = run({ usages, throwOnUsage: true });
// 外部 dispatcher root 的重定向：Brigadier 输出 "prefix ->"（目标 usageText 为空）
const externalRoot = run({
  usages: ["execute ->", "alias -> foo", "loop ...", "plain"],
  throwOnUsage: false,
});
process.stdout.write(JSON.stringify({ ok, broken, externalRoot }));

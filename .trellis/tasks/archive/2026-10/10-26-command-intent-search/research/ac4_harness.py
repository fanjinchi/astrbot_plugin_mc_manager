"""AC4 临时验收 harness（不属于插件运行时）。

用 AstrBot 自身组件跑 5 条中文意图：
- provider: astrbot.core.provider.sources.openai_source.ProviderOpenAIOfficial（真实 provider/model）
- 工具 schema: 从 main.py 的 tool_search_mc_commands docstring 用 AstrBot 同款 docstring_parser 生成，只注册 search_mc_commands
- 工具实现: main.py 里同一调用 kb.commands.search_commands，data_dir 通过 AstrBot StarTools.get_data_dir 解析（独立 ASTRBOT_ROOT）
"""

import asyncio
import ast
import hashlib
import json
import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
ASTRBOT_ROOT = os.environ["ASTRBOT_ROOT"]
CODE_ROOT = "/home/guigui/code/AstrBot"

sys.path.insert(0, CODE_ROOT)
sys.path.insert(0, PLUGIN_DIR)

from docstring_parser import parse as parse_doc  # noqa: E402

from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial  # noqa: E402
from astrbot.core.provider.func_tool_manager import FunctionToolManager as FuncToolManager  # noqa: E402
from astrbot.core.agent.message import AssistantMessageSegment, ToolCallMessageSegment  # noqa: E402
from astrbot.core.provider.entities import ToolCallsResult  # noqa: E402
from astrbot.core.star.star_tools import StarTools  # noqa: E402

from kb import commands as cmd_kb  # noqa: E402

CASES = {
    "Farming": [
        ("把酒陈酿到 10 年", "wine", ["wine age <years>"]),
        ("给 Steve 开启任务编辑模式", "ftbquests", ["ftbquests editing_mode <enabled> <player>"]),
        ("看看老王激活了哪些传送石碑", "waystones", ["waystones list <player> all"]),
    ],
    "CTI": [
        ("清掉全服辐射", "mek", ["mek radiation removeAll"]),
        ("把 AE2 频道模式换一下", "ae2", [
            "ae2 channelmode default",
            "ae2 channelmode infinite",
            "ae2 channelmode x2",
            "ae2 channelmode x3",
            "ae2 channelmode x4",
        ]),
    ],
}

SYSTEM_PROMPT = "你是一个 Minecraft 服务器管理助手。你可以使用提供的工具来查询信息。"


def load_cfg(root):
    path = os.path.join(root, "data", "cmd_config.json")
    return json.load(open(path, encoding="utf-8-sig"))


def build_provider(cfg, provider_id):
    entry = next(p for p in cfg["provider"] if p.get("id") == provider_id)
    source = next(
        s for s in cfg["provider_sources"] if s.get("id") == entry.get("provider_source_id")
    )
    merged = {**source, **entry}
    merged["id"] = entry["id"]
    merged["type"] = source.get("type", merged.get("type"))
    provider = ProviderOpenAIOfficial(merged, cfg.get("provider_settings", {}))
    provider.set_model(entry["model"])
    return provider, entry, source


def build_tool_manager():
    src = open(os.path.join(PLUGIN_DIR, "main.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    node = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "tool_search_mc_commands"
    )
    doc = ast.get_docstring(node)
    parsed = parse_doc(doc)
    py2json = {"str": "string", "int": "number", "float": "number", "bool": "boolean"}
    args = []
    for p in parsed.params:
        args.append(
            {
                "type": py2json.get(p.type_name, p.type_name),
                "name": p.arg_name,
                "description": p.description,
            }
        )

    calls = []

    async def handler(event=None, **kwargs):
        keyword = kwargs.get("keyword", "")
        limit = kwargs.get("limit", 8)
        data_dir = str(StarTools.get_data_dir("astrbot_plugin_mc_manager"))
        text = cmd_kb.search_commands(keyword, limit, data_dir=data_dir)
        calls.append({"name": "search_mc_commands", "keyword": keyword, "limit": limit, "data_dir": data_dir, "output": text})
        return text

    mgr = FuncToolManager()
    mgr.add_func("search_mc_commands", args, parsed.description.strip(), handler)
    return mgr, calls, parsed.description.strip()


async def run_case(provider, mgr, calls, session_id, user_text):
    calls.clear()
    resp = await provider.text_chat(
        prompt=user_text,
        session_id=session_id,
        func_tool=mgr,
        system_prompt=SYSTEM_PROMPT,
        contexts=[],
    )
    contexts = [{"role": "user", "content": user_text}]
    turns = 0
    while resp.tools_call_name and turns < 8:
        turns += 1
        segments = []
        for name, args, call_id in zip(resp.tools_call_name, resp.tools_call_args, resp.tools_call_ids):
            tool = mgr.get_func(name)
            if tool is None:
                segments.append(ToolCallMessageSegment(role="tool", tool_call_id=call_id, content="工具不可用"))
                continue
            out = await tool.handler(None, **args)
            segments.append(ToolCallMessageSegment(role="tool", tool_call_id=call_id, content=out))
        tcr = ToolCallsResult(
            tool_calls_info=AssistantMessageSegment(
                role="assistant",
                content=resp.completion_text or "",
                tool_calls=resp.to_openai_tool_calls_model(),
            ),
            tool_calls_result=segments,
        )
        contexts.extend(tcr.to_openai_messages())
        resp = await provider.text_chat(
            session_id=session_id,
            func_tool=mgr,
            system_prompt=SYSTEM_PROMPT,
            contexts=contexts,
            tool_calls_result=None,
        )
    return resp, turns


async def main():
    group = sys.argv[1]
    provider_id = sys.argv[2]
    out_path = sys.argv[3]

    cfg = load_cfg(ASTRBOT_ROOT)
    provider, entry, source = build_provider(cfg, provider_id)
    mgr, calls, tool_desc = build_tool_manager()
    assert len(mgr.func_list) == 1, "工具集合必须只有 search_mc_commands"

    snapshot = cmd_kb.snapshot_path(str(StarTools.get_data_dir("astrbot_plugin_mc_manager")))
    raw = open(snapshot, "rb").read()
    snap = json.loads(raw.decode("utf-8"))

    results = []
    ok_count = 0
    for index, (user_text, expect_root, expect_syntax) in enumerate(CASES[group], 1):
        session_id = "ac4-%s-%d" % (group, index)
        resp, turns = await run_case(provider, mgr, calls, session_id, user_text)
        outputs = [c["output"] for c in calls]
        blob = "\n".join(outputs)
        root_ok = ("- /%s" % expect_root) in blob
        syntax_ok = all(s in blob for s in expect_syntax)
        called_names = [c["name"] for c in calls]
        non_search = [n for n in called_names if n != "search_mc_commands"]
        passed = root_ok and syntax_ok and not non_search
        ok_count += 1 if passed else 0
        results.append(
            {
                "index": index,
                "user_input": user_text,
                "session_id": session_id,
                "expect_root": expect_root,
                "expect_syntax": expect_syntax,
                "tool_calls": [dict(c) for c in calls],
                "tool_turn_count": turns,
                "hit_turn_cap": bool(resp.tools_call_name),
                "final_text": resp.completion_text,
                "root_ok": root_ok,
                "syntax_ok": syntax_ok,
                "passed": passed,
            }
        )
        print("[%d] %s => root=%s syntax=%s passed=%s turns=%d" % (
            index, user_text, root_ok, syntax_ok, passed, turns))

    evidence = {
        "group": group,
        "astrbot_root": ASTRBOT_ROOT,
        "data_dir": str(StarTools.get_data_dir("astrbot_plugin_mc_manager")),
        "snapshot_path": snapshot,
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "snapshot_producer": snap["producer"],
        "snapshot_count": snap["count"],
        "snapshot_roots": len({e["name"] for e in snap["entries"]}),
        "provider_id": provider_id,
        "provider_source_id": entry.get("provider_source_id"),
        "provider_model": entry.get("model"),
        "provider_type": source.get("type"),
        "tool_count": len(mgr.func_list),
        "tool_name": mgr.func_list[0].name,
        "tool_description_sha256": hashlib.sha256(tool_desc.encode("utf-8")).hexdigest(),
        "system_prompt": SYSTEM_PROMPT,
        "passed": "%d/%d" % (ok_count, len(CASES[group])),
        "results": results,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, ensure_ascii=False, indent=1)
    print("SUMMARY %s %d/%d -> %s" % (group, ok_count, len(CASES[group]), out_path))
    return 0 if ok_count == len(CASES[group]) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

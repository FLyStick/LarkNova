"""环境自检：诊断飞书身份可见性、读消息权限与数据边界配置。"""

from __future__ import annotations

from typing import Any

from feishu_agent.feishu.client import FeishuClient, FeishuError
from feishu_agent.sync.runner import boundary_reason

PERMISSION_HINT = (
    "在飞书开发者后台为应用开启 im:message:readonly，"
    "然后将 LARK_IDENTITY 设为 bot 后重试。"
)


def run_doctor(
    client: FeishuClient,
    identity: str | None = None,
    allowed_chat_ids: set[str] | None = None,
    allow_external: bool = False,
    max_read_checks: int = 1,
) -> dict[str, Any]:
    """执行一轮环境体检，返回平台/权限/边界问题与可执行的修复建议。"""
    who = identity or client.identity
    result: dict[str, Any] = {
        "identity": who,
        "boundary": {
            "allow_external": allow_external,
            "whitelist": sorted(allowed_chat_ids) if allowed_chat_ids else [],
        },
        "chats_found": 0,
        "chats_allowed": 0,
        "chats_skipped": [],
        "whitelist_missing": [],
        "read_check": None,
        "blockers": [],
        "fixes": [],
        "ok": False,
    }

    try:
        chats = client.list_chats(identity=who)
    except FeishuError as exc:
        result["blockers"].append({"stage": "chat_list", "code": exc.code, "error": str(exc)})
        if exc.code == 230027:
            result["fixes"].append(PERMISSION_HINT)
        return result
    except Exception as exc:
        result["blockers"].append({"stage": "chat_list", "error": str(exc)})
        return result

    found_ids = {str(chat.get("chat_id")) for chat in chats if chat.get("chat_id")}
    if allowed_chat_ids is not None:
        missing = sorted(allowed_chat_ids - found_ids)
        if missing:
            result["whitelist_missing"] = missing
            result["fixes"].append(
                f"白名单中以下群未在机器人可见列表中出现：{', '.join(missing)}"
            )

    allowed_chats: list[dict[str, Any]] = []
    for chat in chats:
        chat_id = chat.get("chat_id")
        if not chat_id:
            result["chats_skipped"].append(
                {"chat_id": None, "chat_name": chat.get("name", ""), "reason": "missing_chat_id"}
            )
            continue
        reason = boundary_reason(
            str(chat_id),
            bool(chat.get("external")),
            allowed_chat_ids,
            allow_external,
        )
        if reason:
            result["chats_skipped"].append(
                {"chat_id": str(chat_id), "chat_name": chat.get("name", ""), "reason": reason}
            )
        else:
            allowed_chats.append(chat)

    result["chats_found"] = len(chats)
    result["chats_allowed"] = len(allowed_chats)

    if any(item.get("reason") == "external_chat" for item in result["chats_skipped"]):
        result["fixes"].append("如需纳入外部群，请谨慎设置 FEISHU_AGENT_ALLOW_EXTERNAL_CHATS=1。")

    for chat in allowed_chats[:max_read_checks]:
        chat_id = str(chat.get("chat_id"))
        try:
            messages = client.list_messages(
                chat_id,
                identity=who,
                order="desc",
                page_size=1,
                page_all=False,
            )
            result["read_check"] = {
                "chat_id": chat_id,
                "chat_name": chat.get("name", ""),
                "ok": True,
                "messages_count": len(messages),
            }
            break
        except FeishuError as exc:
            result["read_check"] = {
                "chat_id": chat_id,
                "chat_name": chat.get("name", ""),
                "ok": False,
                "code": exc.code,
                "error": str(exc),
            }
            if exc.code == 230027:
                result["blockers"].append(
                    {"stage": "message_list", "code": exc.code, "error": str(exc)}
                )
                result["fixes"].append(PERMISSION_HINT)
            else:
                result["blockers"].append(
                    {"stage": "message_list", "code": exc.code, "error": str(exc)}
                )
            break
        except Exception as exc:
            result["read_check"] = {
                "chat_id": chat_id,
                "chat_name": chat.get("name", ""),
                "ok": False,
                "error": str(exc),
            }
            result["blockers"].append({"stage": "message_list", "error": str(exc)})
            break

    if not result["blockers"]:
        result["ok"] = True
    return result


def format_doctor(result: dict[str, Any]) -> str:
    """把体检结果格式化成适合 CLI 展示的多行文本。"""
    lines = [
        f"identity: {result['identity']}",
        "boundary: whitelist={} allow_external={}".format(
            result["boundary"]["whitelist"] or "(all)",
            result["boundary"]["allow_external"],
        ),
        f"chats_found: {result['chats_found']}, chats_allowed: {result['chats_allowed']}",
    ]
    for item in result["chats_skipped"]:
        lines.append(f"  skipped: {item.get('chat_id')} ({item.get('reason')})")
    if result["read_check"]:
        check = result["read_check"]
        status = "ok" if check["ok"] else f"failed ({check.get('code')})"
        lines.append(f"read_check: {check.get('chat_id')} -> {status}")
    for blocker in result["blockers"]:
        suffix = " ".join(str(blocker.get(k, "")) for k in ("code", "error") if blocker.get(k))
        lines.append(f"blocker: {blocker.get('stage')}: {suffix}".rstrip())
    for fix in result["fixes"]:
        lines.append(f"fix: {fix}")
    return "\n".join(lines)

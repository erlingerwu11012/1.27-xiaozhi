#!/usr/bin/env python3
"""update_spine 运维入口。

查询本地审计镜像；取消操作同步 manager-api 中央库（权威），本地 SQLite 仅作镜像。

  查询某设备全部任务（本地审计镜像）：
    python scripts/spine_ota_admin.py list --device-id ac:a7:04:fd:20:5c

  列出所有仍可能重投的卡死任务（本地审计镜像，非终态）：
    python scripts/spine_ota_admin.py list --stuck

  取消指定设备 pending/queued/sent/in_progress 的 update_spine（同步中央库 + 本地镜像）：
    python scripts/spine_ota_admin.py cancel --device-id ac:a7:04:fd:20:5c --reason reboot_loop

  查看单个任务（本地审计镜像）：
    python scripts/spine_ota_admin.py show --task-id <uuid>
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from core.utils import spine_ota_store  # noqa: E402


def _print_rows(rows):
    if not rows:
        print("(empty)")
        return
    header = (
        "task_id | device_id | pack_id | state | attempt_count | "
        "last_sent_at | next_attempt_at | completed_at | error_code | cancel_reason"
    )
    print(header)
    for r in rows:
        d = spine_ota_store.render_delivery(r)
        print(
            f"{d['task_id']} | {d['device_id']} | {d.get('pack_id')} | {d['state']} | "
            f"{d['attempt_count']} | {d.get('last_sent_at')} | {d.get('next_attempt_at')} | "
            f"{d.get('completed_at')} | {d.get('error_code')} | {d.get('cancel_reason')}"
        )


def _load_config() -> dict:
    from config.config_loader import get_project_dir, read_config, merge_configs

    default = read_config(get_project_dir() + "config.yaml")
    custom_path = get_project_dir() + "data/.config.yaml"
    custom = read_config(custom_path) if os.path.exists(custom_path) else {}
    return merge_configs(default, custom)


def _central_cancel(device_id: str, reason: str):
    """同步 manager-api 中央库取消（权威），返回中央结果 dict；失败返回 None。"""
    try:
        from config.manage_api_client import ManageApiClient, init_service

        init_service(_load_config())
        return ManageApiClient._instance._execute_request(
            "POST",
            "role-packs/device/cancel-pending-spine",
            params={"deviceId": device_id, "reason": reason},
        )
    except Exception as e:  # noqa: BLE001
        print(f"警告: 中央库取消失败: {e}", file=sys.stderr)
        return None


def cmd_list(args):
    if args.stuck:
        rows = spine_ota_store.list_stuck()
        print(f"stuck (non-terminal) tasks: {len(rows)}")
        _print_rows(rows)
        return
    if not args.device_id:
        print("请提供 --device-id 或 --stuck", file=sys.stderr)
        sys.exit(2)
    rows = spine_ota_store.list_device(args.device_id)
    print(f"tasks for device {args.device_id}: {len(rows)}")
    _print_rows(rows)


def cmd_cancel(args):
    if not args.device_id:
        print("请提供 --device-id", file=sys.stderr)
        sys.exit(2)
    reason = args.reason or "manual_cancel"
    central = _central_cancel(args.device_id, reason)
    if central is not None:
        tasks = central.get("tasks") or []
        count = central.get("cancelledCount", len(tasks))
        print(f"central cancelled {count} update_spine task(s) for device {args.device_id}")
        for t in tasks:
            tid = t.get("taskId") or t.get("task_id") if isinstance(t, dict) else t
            print(f"  - {tid} -> cancelled")
    # 本地审计镜像（best-effort）
    local = spine_ota_store.cancel_device(args.device_id, reason=reason)
    print(f"local mirror cancelled {len(local)} task(s)")


def cmd_show(args):
    if not args.task_id:
        print("请提供 --task-id", file=sys.stderr)
        sys.exit(2)
    d = spine_ota_store.get_delivery(args.task_id)
    if not d:
        print("not found")
        return
    print(json.dumps(spine_ota_store.render_delivery(d), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="update_spine 运维入口")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出任务（本地审计镜像）")
    p_list.add_argument("--device-id", default=None)
    p_list.add_argument("--stuck", action="store_true", help="列出所有非终态任务")

    p_cancel = sub.add_parser("cancel", help="取消指定设备的 update_spine 任务（同步中央库）")
    p_cancel.add_argument("--device-id", required=True)
    p_cancel.add_argument("--reason", default=None)

    p_show = sub.add_parser("show", help="查看单个任务（本地审计镜像）")
    p_show.add_argument("--task-id", required=True)

    args = parser.parse_args()
    if args.command == "list":
        cmd_list(args)
    elif args.command == "cancel":
        cmd_cancel(args)
    elif args.command == "show":
        cmd_show(args)


if __name__ == "__main__":
    main()

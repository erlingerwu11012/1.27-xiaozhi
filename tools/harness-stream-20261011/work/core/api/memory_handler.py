"""
记忆管理 HTTP 接口处理器。
提供记忆的查询、删除功能，供智控台 UI 使用。
"""
import json
from aiohttp import web
from config.logger import setup_logging
from core.utils.db_memory import get_all_memories_for_admin, delete_memory_by_id, get_memories_by_device, delete_memories_by_device

TAG = __name__


class MemoryHandler:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()

    def _add_cors_headers(self, response):
        response.headers["Access-Control-Allow-Headers"] = (
            "authorization, client-id, content-type, device-id"
        )
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, DELETE, OPTIONS"

    async def handle_options(self, request):
        response = web.Response(status=204)
        self._add_cors_headers(response)
        return response

    async def handle_list(self, request):
        """GET /admin/memory?device_id=xxx&page=1&limit=20"""
        try:
            device_id = request.rel_url.query.get("device_id", "").strip()
            page = max(1, int(request.rel_url.query.get("page", 1)))
            limit = min(100, max(1, int(request.rel_url.query.get("limit", 20))))

            if device_id:
                records = get_memories_by_device(device_id)
            else:
                records = get_all_memories_for_admin()

            total = len(records)
            start = (page - 1) * limit
            page_records = records[start: start + limit]

            response = web.Response(
                text=json.dumps({
                    "code": 0,
                    "data": {
                        "list": page_records,
                        "total": total,
                        "page": page,
                        "limit": limit,
                    }
                }, ensure_ascii=False),
                content_type="application/json",
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"查询记忆失败: {e}")
            response = web.Response(
                text=json.dumps({"code": 500, "msg": str(e)}),
                content_type="application/json",
                status=500,
            )
        self._add_cors_headers(response)
        return response

    async def handle_delete(self, request):
        """DELETE /admin/memory/{id}"""
        try:
            memory_id = int(request.match_info["id"])
            ok = delete_memory_by_id(memory_id)
            response = web.Response(
                text=json.dumps({"code": 0, "data": ok}),
                content_type="application/json",
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"删除记忆失败: {e}")
            response = web.Response(
                text=json.dumps({"code": 500, "msg": str(e)}),
                content_type="application/json",
                status=500,
            )
        self._add_cors_headers(response)
        return response

    async def handle_delete_by_device(self, request):
        """DELETE /admin/memory/device/{device_id} — 清空某设备全部记忆"""
        try:
            device_id = request.match_info["device_id"]
            count = delete_memories_by_device(device_id)
            response = web.Response(
                text=json.dumps({"code": 0, "data": count}),
                content_type="application/json",
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"清空设备记忆失败: {e}")
            response = web.Response(
                text=json.dumps({"code": 500, "msg": str(e)}),
                content_type="application/json",
                status=500,
            )
        self._add_cors_headers(response)
        return response

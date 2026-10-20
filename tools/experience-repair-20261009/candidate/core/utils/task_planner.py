"""
任务规划器：Plan-then-Execute 层。
复杂任务时，先让 LLM 生成结构化计划（JSON 步骤列表），
然后按步骤执行，每步 checkpoint 确认状态，支持中断恢复。
"""
import json
import os
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 计划持久化目录
_PLANS_DIR = Path(os.environ.get(
    "TASK_PLANS_DIR",
    os.environ.get("AGENT_PERSONAS_DIR", "/tmp") + "/task_plans"
))

# 复杂任务判断关键词
COMPLEX_TASK_KEYWORDS = [
    "帮我下载", "帮我安装", "帮我部署", "帮我配置",
    "帮我搭建", "帮我创建项目", "帮我设置",
    "下载并安装", "打开并操作", "搜索并下载",
    "一步一步", "按步骤", "完整流程",
]

# 计划生成 prompt
PLAN_GENERATION_PROMPT = """你需要为以下任务生成一个结构化执行计划。
请以 JSON 格式输出，包含 steps 数组，每步包含：
- action: 要调用的工具名称
- params: 工具参数（对象）
- description: 这一步做什么（简短中文描述）
- checkpoint: 是否需要在执行后确认状态（布尔值）

只输出 JSON，不要其他文字。示例格式：
{"task": "任务描述", "steps": [{"action": "browser_open", "params": {"url": "..."}, "description": "打开官网", "checkpoint": true}]}

用户任务：{task}"""


class TaskPlan:
    """单个任务计划。"""

    def __init__(self, task: str, steps: List[Dict[str, Any]], device_id: str = "default"):
        self.task = task
        self.steps = steps
        self.device_id = device_id
        self.current_step = 0
        self.status = "pending"  # pending | running | paused | completed | failed
        self.created_at = time.time()
        self.results: List[Dict[str, Any]] = []

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "steps": self.steps,
            "device_id": self.device_id,
            "current_step": self.current_step,
            "status": self.status,
            "created_at": self.created_at,
            "results": self.results,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskPlan":
        plan = cls(
            task=data["task"],
            steps=data["steps"],
            device_id=data.get("device_id", "default"),
        )
        plan.current_step = data.get("current_step", 0)
        plan.status = data.get("status", "pending")
        plan.created_at = data.get("created_at", time.time())
        plan.results = data.get("results", [])
        return plan

    @property
    def is_complete(self) -> bool:
        return self.current_step >= len(self.steps)

    @property
    def current_step_info(self) -> Optional[Dict[str, Any]]:
        if self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None

    def advance(self, result: str = "") -> bool:
        """推进到下一步，返回是否还有后续步骤。"""
        self.results.append({
            "step": self.current_step,
            "result": result[:500],  # 截断过长结果
            "timestamp": time.time(),
        })
        self.current_step += 1
        if self.is_complete:
            self.status = "completed"
            return False
        return True

    def get_progress_summary(self) -> str:
        """返回当前进度摘要，用于注入 LLM 上下文。"""
        total = len(self.steps)
        done = self.current_step
        lines = [f"任务计划：{self.task}（进度 {done}/{total}）"]
        if self.current_step_info:
            step = self.current_step_info
            lines.append(f"当前步骤：{step.get('description', step.get('action', ''))}")
        if self.results:
            last = self.results[-1]
            lines.append(f"上一步结果：{last['result'][:100]}")
        return "\n".join(lines)


class TaskPlanner:
    """任务规划器：管理设备级任务计划。"""

    def __init__(self):
        self._plans: Dict[str, TaskPlan] = {}
        _PLANS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_persisted_plans()

    def _load_persisted_plans(self):
        """启动时加载未完成的持久化计划。"""
        for f in _PLANS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                plan = TaskPlan.from_dict(data)
                if plan.status in ("pending", "running", "paused"):
                    self._plans[plan.device_id] = plan
                    logger.info(f"恢复未完成计划: {plan.task} (设备 {plan.device_id})")
            except Exception as e:
                logger.warning(f"加载计划 {f.name} 失败: {e}")

    def _persist_plan(self, plan: TaskPlan):
        """持久化计划到文件。"""
        try:
            path = _PLANS_DIR / f"{plan.device_id}.json"
            path.write_text(
                json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"持久化计划失败: {e}")

    def _remove_plan_file(self, device_id: str):
        """删除已完成的计划文件。"""
        try:
            path = _PLANS_DIR / f"{device_id}.json"
            if path.exists():
                path.unlink()
        except Exception:
            pass

    @staticmethod
    def is_complex_task(query: str) -> bool:
        """判断是否为复杂任务（需要多步规划）。"""
        if not query:
            return False
        return any(kw in query for kw in COMPLEX_TASK_KEYWORDS)

    def has_active_plan(self, device_id: str) -> bool:
        """检查设备是否有活跃计划。"""
        plan = self._plans.get(device_id)
        return plan is not None and plan.status in ("pending", "running", "paused")

    def get_active_plan(self, device_id: str) -> Optional[TaskPlan]:
        """获取设备的活跃计划。"""
        plan = self._plans.get(device_id)
        if plan and plan.status in ("pending", "running", "paused"):
            return plan
        return None

    def create_plan(self, device_id: str, task: str, steps: List[Dict[str, Any]]) -> TaskPlan:
        """创建新计划。"""
        plan = TaskPlan(task=task, steps=steps, device_id=device_id)
        plan.status = "running"
        self._plans[device_id] = plan
        self._persist_plan(plan)
        logger.info(f"创建任务计划: {task} ({len(steps)} 步)")
        return plan

    def advance_plan(self, device_id: str, result: str = "") -> Optional[TaskPlan]:
        """推进计划到下一步，返回更新后的计划。"""
        plan = self.get_active_plan(device_id)
        if not plan:
            return None
        has_more = plan.advance(result)
        self._persist_plan(plan)
        if not has_more:
            self._remove_plan_file(device_id)
            logger.info(f"任务计划完成: {plan.task}")
        return plan

    def cancel_plan(self, device_id: str):
        """取消计划。"""
        plan = self._plans.pop(device_id, None)
        if plan:
            plan.status = "cancelled"
            self._remove_plan_file(device_id)
            logger.info(f"任务计划已取消: {plan.task}")

    def get_plan_prompt_suffix(self, device_id: str) -> str:
        """获取当前计划的 prompt 后缀，用于注入 LLM 上下文。"""
        plan = self.get_active_plan(device_id)
        if not plan:
            return ""
        step = plan.current_step_info
        if not step:
            return ""
        return (
            f"\n\n--- 任务计划执行中 ---\n"
            f"{plan.get_progress_summary()}\n"
            f"请执行当前步骤：调用 {step.get('action', '')} 工具，"
            f"参数参考：{json.dumps(step.get('params', {}), ensure_ascii=False)}\n"
            f"说明：{step.get('description', '')}"
        )

    @staticmethod
    def get_plan_generation_prompt(task: str) -> str:
        """返回让 LLM 生成计划的 prompt。"""
        return PLAN_GENERATION_PROMPT.format(task=task)

    @staticmethod
    def parse_plan_from_llm_response(response: str) -> Optional[List[Dict[str, Any]]]:
        """从 LLM 响应中解析计划 JSON。"""
        try:
            # 尝试直接解析
            data = json.loads(response)
            if isinstance(data, dict) and "steps" in data:
                return data["steps"]
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # 尝试从文本中提取 JSON
        import re
        json_match = re.search(r'\{[\s\S]*"steps"\s*:\s*\[[\s\S]*\]\s*\}', response)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return data.get("steps", [])
            except json.JSONDecodeError:
                pass

        return None

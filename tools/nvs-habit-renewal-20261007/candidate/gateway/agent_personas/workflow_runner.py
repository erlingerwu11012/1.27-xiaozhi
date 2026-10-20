"""
工作流调度器：解析 workflows/*.yaml，匹配用户意图，
返回当前阶段的角色 + 工具限制 + prompt 后缀。

借鉴 Claude Code feature-dev 插件的多阶段 Command 编排模式。
工作流不直接执行工具，而是为 PromptManager 提供「当前阶段应该用什么角色、
什么工具、什么额外指令」的元数据，由 LLM 自行决定具体操作。
"""
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None
    logger.warning("pyyaml 未安装，工作流功能不可用。建议: pip install pyyaml")


class WorkflowRunner:
    """工作流调度器：管理设备级工作流状态。"""

    def __init__(self, base_dir: str | Path | None = None):
        base = Path(base_dir) if base_dir else Path(
            os.environ.get("AGENT_PERSONAS_DIR", str(Path(__file__).parent))
        )
        self.workflows_dir = base / "workflows"
        self._workflows: dict[str, dict] = {}
        self._device_state: dict[str, dict] = {}  # {device_id: {workflow, phase_idx}}
        self._load_workflows()

    def _load_workflows(self):
        """扫描并加载所有工作流定义。"""
        if yaml is None or not self.workflows_dir.exists():
            return
        for p in self.workflows_dir.glob("*.yaml"):
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
                if data and "name" in data and "phases" in data:
                    self._workflows[p.stem] = data
            except Exception as e:
                logger.error(f"加载工作流 {p.name} 失败: {e}")
        if self._workflows:
            logger.info(f"📋 已加载 {len(self._workflows)} 个工作流")

    def list_workflows(self) -> list[dict]:
        """返回所有可用工作流的摘要。"""
        return [
            {"id": k, "name": v["name"], "keywords": v.get("trigger_keywords", [])}
            for k, v in self._workflows.items()
        ]

    def match_workflow(self, user_text: str) -> Optional[str]:
        """根据用户文本匹配工作流，返回工作流 ID 或 None。"""
        text = user_text.lower()
        for wf_id, wf in self._workflows.items():
            keywords = wf.get("trigger_keywords", [])
            for kw in keywords:
                if kw.lower() in text:
                    return wf_id
        return None

    def start_workflow(self, device_id: str, workflow_id: str) -> Optional[dict]:
        """启动工作流，返回第一阶段的元数据。"""
        wf = self._workflows.get(workflow_id)
        if not wf or not wf.get("phases"):
            return None
        self._device_state[device_id] = {
            "workflow_id": workflow_id,
            "phase_idx": 0,
        }
        return self._get_current_phase(device_id)

    def advance_phase(self, device_id: str) -> Optional[dict]:
        """推进到下一阶段，返回新阶段元数据；若已完成返回 None。"""
        state = self._device_state.get(device_id)
        if not state:
            return None
        wf = self._workflows.get(state["workflow_id"])
        if not wf:
            return None
        state["phase_idx"] += 1
        if state["phase_idx"] >= len(wf["phases"]):
            # 工作流完成
            del self._device_state[device_id]
            return None
        return self._get_current_phase(device_id)

    def get_current_phase(self, device_id: str) -> Optional[dict]:
        """获取当前阶段元数据（外部调用）。"""
        return self._get_current_phase(device_id)

    def is_in_workflow(self, device_id: str) -> bool:
        """设备是否正在执行工作流。"""
        return device_id in self._device_state

    def cancel_workflow(self, device_id: str):
        """取消当前工作流。"""
        self._device_state.pop(device_id, None)

    def _get_current_phase(self, device_id: str) -> Optional[dict]:
        """获取当前阶段的完整元数据。"""
        state = self._device_state.get(device_id)
        if not state:
            return None
        wf = self._workflows.get(state["workflow_id"])
        if not wf:
            return None
        phases = wf.get("phases", [])
        idx = state["phase_idx"]
        if idx >= len(phases):
            return None
        phase = phases[idx]
        return {
            "workflow_name": wf["name"],
            "phase_name": phase["name"],
            "phase_index": idx,
            "total_phases": len(phases),
            "role": phase.get("role", "default"),
            "allowed_tools": phase.get("tools"),
            "prompt_suffix": phase.get("prompt_suffix", ""),
        }

    def get_workflow_prompt_suffix(self, device_id: str) -> str:
        """为 PromptManager 生成工作流阶段的 prompt 后缀。"""
        phase = self._get_current_phase(device_id)
        if not phase:
            return ""
        return (
            f"\n\n--- 工作流：{phase['workflow_name']} ---\n"
            f"当前阶段：{phase['phase_name']}（{phase['phase_index'] + 1}/{phase['total_phases']}）\n"
            f"任务指令：{phase['prompt_suffix']}\n"
            f"完成本阶段后请明确告知用户，等待确认后进入下一阶段。"
        )

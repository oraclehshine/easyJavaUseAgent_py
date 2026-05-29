import json
from typing import Any

from app.registry import get_capability


class AgentError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def route_and_execute(task_type: str, payload_json: str) -> dict[str, Any]:
    capability = get_capability(task_type)
    if capability is None:
        raise AgentError("AGENT_CAPABILITY_NOT_FOUND", f"task_type not found: {task_type}")

    payload = json.loads(payload_json) if payload_json else {}

    if task_type == "study_plan.generate":
        return {
            "capability": task_type,
            "plan": [
                {"day": "Mon", "topic": f"{payload.get('subject', 'math')} basics", "duration_min": 45},
                {"day": "Tue", "topic": "error review", "duration_min": 30},
            ],
        }

    if task_type == "paper.generate":
        return {
            "capability": task_type,
            "paper": [
                {"id": "q1", "type": "single_choice", "difficulty": payload.get("difficulty", "medium")},
                {"id": "q2", "type": "short_answer", "difficulty": "medium"},
            ],
        }

    if task_type == "report.generate":
        return {
            "capability": task_type,
            "summary": "This week study completion is 82%, focus on geometry mistakes.",
        }

    raise AgentError("AGENT_TASK_UNSUPPORTED", f"unsupported task_type: {task_type}")

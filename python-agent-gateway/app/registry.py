from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Capability:
    name: str
    version: str
    description: str
    input_schema_json: str
    output_schema_json: str
    supports_streaming: bool = False


CAPABILITIES: Dict[str, Capability] = {
    "study_plan.generate": Capability(
        name="study_plan.generate",
        version="v1",
        description="Generate weekly study plan for K12 student",
        input_schema_json='{"type":"object","properties":{"grade":{"type":"string"},"subject":{"type":"string"}}}',
        output_schema_json='{"type":"object","properties":{"plan":{"type":"array"}}}',
        supports_streaming=True,
    ),
    "paper.generate": Capability(
        name="paper.generate",
        version="v1",
        description="Generate practice paper by knowledge point and difficulty",
        input_schema_json='{"type":"object","properties":{"subject":{"type":"string"},"difficulty":{"type":"string"}}}',
        output_schema_json='{"type":"object","properties":{"paper":{"type":"array"}}}',
        supports_streaming=False,
    ),
    "report.generate": Capability(
        name="report.generate",
        version="v1",
        description="Generate learning report summary",
        input_schema_json='{"type":"object","properties":{"student_id":{"type":"string"}}}',
        output_schema_json='{"type":"object","properties":{"summary":{"type":"string"}}}',
        supports_streaming=False,
    ),
}


def list_capabilities() -> List[Capability]:
    return list(CAPABILITIES.values())


def get_capability(task_type: str) -> Capability | None:
    return CAPABILITIES.get(task_type)

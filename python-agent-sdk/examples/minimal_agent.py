import json

from easy_java_agent_sdk import AgentBridgeApp

app = AgentBridgeApp(agent_name="school-assistant", agent_version="1.0.0")


@app.capability(
    name="study_plan.generate",
    description="Generate study guidance for K12 student",
    input_schema_json='{"type":"object","properties":{"grade":{"type":"string"},"subject":{"type":"string"}}}',
    output_schema_json='{"type":"object"}',
)
def generate_plan(payload_json: str) -> dict:
    payload = json.loads(payload_json or "{}")
    return {
        "plan": [
            f"Review last week {payload.get('subject', 'subject')} mistakes",
            "Daily 30-min targeted practice",
            "Weekend mock quiz and summary",
        ],
        "grade": payload.get("grade", "unknown"),
        "subject": payload.get("subject", "unknown"),
    }


@app.stream_capability("study_plan.generate")
def generate_plan_stream(payload_json: str):
    payload = json.loads(payload_json or "{}")
    yield {"stage": "analysis", "subject": payload.get("subject", "unknown")}
    yield {"stage": "planning", "tips": ["focus errors", "short loop feedback"]}
    yield {"stage": "done"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=50051)

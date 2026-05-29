import json
from jsonschema import validate, ValidationError

from app.registry import get_capability


class ValidationErr(Exception):
    pass


def validate_payload(task_type: str, payload_json: str) -> dict:
    cap = get_capability(task_type)
    if cap is None:
        raise ValidationErr(f"capability not found: {task_type}")

    try:
        payload = json.loads(payload_json) if payload_json else {}
    except Exception as e:
        raise ValidationErr(f"invalid payload json: {e}") from e

    try:
        schema = json.loads(cap.input_schema_json)
        validate(instance=payload, schema=schema)
    except ValidationError as e:
        raise ValidationErr(f"payload schema validation failed: {e.message}") from e
    except Exception as e:
        raise ValidationErr(f"invalid capability schema: {e}") from e

    if len(payload_json or "") > 64 * 1024:
        raise ValidationErr("payload too large")

    return payload

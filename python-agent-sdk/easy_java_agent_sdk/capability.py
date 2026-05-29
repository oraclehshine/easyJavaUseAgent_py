from dataclasses import dataclass
from typing import Callable


@dataclass
class CapabilitySpec:
    name: str
    version: str = "1.0.0"
    description: str = ""
    input_schema_json: str = "{}"
    output_schema_json: str = "{}"
    supports_streaming: bool = False
    handler: Callable[[str], dict] | None = None
    stream_handler: Callable[[str], list[dict]] | None = None

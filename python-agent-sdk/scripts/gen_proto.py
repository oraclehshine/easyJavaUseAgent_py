import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROTO = ROOT / "easy_java_agent_sdk" / "proto" / "agent_bridge.proto"
OUT = ROOT / "easy_java_agent_sdk" / "proto"

cmd = [
    sys.executable,
    "-m",
    "grpc_tools.protoc",
    f"-I{PROTO.parent}",
    f"--python_out={OUT}",
    f"--grpc_python_out={OUT}",
    str(PROTO),
]
print(" ".join(cmd))
subprocess.check_call(cmd)
print("proto generated")

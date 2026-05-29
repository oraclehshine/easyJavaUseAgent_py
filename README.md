# easyJavaUseAgent_py

Python side projects for `easyJavaUseAgent`.

## Projects

1. `python-agent-gateway`
- Production-oriented gRPC gateway for AgentBridge
- Supports TLS/mTLS, JWT (HS256/RS256/JWKS), async task status, readiness/metrics

2. `python-agent-sdk`
- Lightweight SDK adapter to expose existing Python agent logic with minimal code changes
- Supports AgentBridge RPCs: probe/list/invoke/invoke-stream/invoke-async/task-status

## Quick Start

### A. Gateway mode

```bash
cd python-agent-gateway
pip install -r requirements.txt
python server.py
```

### B. SDK mode

```bash
cd python-agent-sdk
pip install -r requirements.txt
python scripts/gen_proto.py
pip install -e .
python examples/minimal_agent.py
```

## Java CLI Integration

Use the Java CLI from the Java repository to validate connectivity:

```bash
java -jar agent-bridge-cli-all.jar probe --host 127.0.0.1 --port 50051
java -jar agent-bridge-cli-all.jar list-capabilities --host 127.0.0.1 --port 50051
java -jar agent-bridge-cli-all.jar invoke --task-type study_plan.generate --payload "{\"grade\":\"6\",\"subject\":\"math\"}"
```

## Notes

- Keep Python and Java proto definitions aligned (`agent_bridge.proto`).
- For production, enable TLS/JWT and avoid plaintext mode.

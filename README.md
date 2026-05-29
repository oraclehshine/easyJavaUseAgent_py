# easyJavaUseAgent_py

这是 `easyJavaUseAgent` 的 Python 侧项目集合。

## 项目说明

1. `python-agent-gateway`
- 面向生产的 AgentBridge gRPC 网关
- 支持 TLS/mTLS、JWT（HS256/RS256/JWKS）、异步任务状态查询、readiness/metrics

2. `python-agent-sdk`
- 轻量级 SDK 适配层
- 在尽量不改原有 Python Agent 逻辑的前提下，快速暴露为 AgentBridge 协议能力
- 支持 RPC：`probe/list/invoke/invoke-stream/invoke-async/task-status`

## 快速启动

### A. Gateway 模式

```bash
cd python-agent-gateway
pip install -r requirements.txt
python server.py
```

### B. SDK 模式

```bash
cd python-agent-sdk
pip install -r requirements.txt
python scripts/gen_proto.py
pip install -e .
python examples/minimal_agent.py
```

## 与 Java 侧联调

使用 Java 仓库里的 CLI 验证连通性：

```bash
java -jar agent-bridge-cli-all.jar probe --host 127.0.0.1 --port 50051
java -jar agent-bridge-cli-all.jar list-capabilities --host 127.0.0.1 --port 50051
java -jar agent-bridge-cli-all.jar invoke --task-type study_plan.generate --payload "{\"grade\":\"6\",\"subject\":\"math\"}"
```

## 注意事项

- Python 与 Java 需要保持同一份 `agent_bridge.proto` 协议定义。
- 生产环境建议开启 TLS/JWT，不建议明文传输。

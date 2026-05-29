# easy-java-agent-sdk

这个 SDK 的目标是：

- 不改你原有 Python Agent 业务逻辑
- 只通过“注册能力 + 启动桥接服务”
- 让 Java Maven 插件通过 AgentBridge gRPC 协议直接调用

## 1. 目录

- `easy_java_agent_sdk/`: SDK 核心
- `easy_java_agent_sdk/proto/agent_bridge.proto`: 协议定义（与 Java 侧一致）
- `scripts/gen_proto.py`: 生成 Python gRPC stub
- `examples/minimal_agent.py`: 最小接入示例

## 2. 安装与生成

```bash
pip install -r requirements.txt
python scripts/gen_proto.py
pip install -e .
```

## 3. 接入你已有 Agent

```python
from easy_java_agent_sdk import AgentBridgeApp

app = AgentBridgeApp(agent_name="your-agent", agent_version="1.0.0")

@app.capability(name="study_plan.generate")
def your_existing_handler(payload_json: str) -> dict:
    # 复用你现有逻辑
    return {"ok": True}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=50051)
```

## 4. Java 侧联调

```bash
java -jar agent-bridge-cli-all.jar probe --host 127.0.0.1 --port 50051
java -jar agent-bridge-cli-all.jar list-capabilities --host 127.0.0.1 --port 50051
java -jar agent-bridge-cli-all.jar invoke --task-type study_plan.generate --payload "{}"
```

## 5. 能力覆盖

SDK 当前支持：

- `ProbeAgent`
- `ListCapabilities`
- `Invoke`
- `InvokeStream`
- `SubmitTask`
- `GetTaskStatus`

## 6. 与原 Agent 共存建议

- 业务 API（FastAPI/Django/MCP）保持不变
- 新起一个 SDK Bridge 进程（50051）
- 该进程只做协议转换与能力暴露

这样你就能做到“原系统零侵入 + Java/Python 打通”。

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import grpc

from .capability import CapabilitySpec


class _TaskRecord:
    def __init__(self, task_id: str, request_id: str):
        now = int(time.time() * 1000)
        self.task_id = task_id
        self.request_id = request_id
        self.status = "PENDING"
        self.result_json = "{}"
        self.error_code = ""
        self.error_message = ""
        self.created_at_epoch_ms = now
        self.updated_at_epoch_ms = now

    def touch(self):
        self.updated_at_epoch_ms = int(time.time() * 1000)


class AgentBridgeApp:
    def __init__(self, agent_name: str = "python-agent", agent_version: str = "1.0.0") -> None:
        self.agent_name = agent_name
        self.agent_version = agent_version
        self._caps: dict[str, CapabilitySpec] = {}
        self._tasks: dict[str, _TaskRecord] = {}
        self._pool = ThreadPoolExecutor(max_workers=8)

    def capability(
        self,
        name: str,
        version: str = "1.0.0",
        description: str = "",
        input_schema_json: str = "{}",
        output_schema_json: str = "{}",
        supports_streaming: bool = False,
    ):
        def deco(func):
            spec = CapabilitySpec(
                name=name,
                version=version,
                description=description,
                input_schema_json=input_schema_json,
                output_schema_json=output_schema_json,
                supports_streaming=supports_streaming,
                handler=func,
                stream_handler=None,
            )
            self._caps[name] = spec
            return func

        return deco

    def stream_capability(self, name: str):
        def deco(func):
            if name not in self._caps:
                self._caps[name] = CapabilitySpec(name=name, supports_streaming=True)
            self._caps[name].supports_streaming = True
            self._caps[name].stream_handler = func
            return func

        return deco

    def _execute(self, task_type: str, payload_json: str) -> dict:
        cap = self._caps.get(task_type)
        if not cap or not cap.handler:
            raise ValueError(f"unknown capability: {task_type}")
        result = cap.handler(payload_json)
        return result if isinstance(result, dict) else {"result": result}

    def _build_servicer(self):
        from .proto import agent_bridge_pb2, agent_bridge_pb2_grpc

        app = self

        class Servicer(agent_bridge_pb2_grpc.AgentBridgeServiceServicer):
            def ProbeAgent(self, request, context):
                caps = [
                    agent_bridge_pb2.Capability(
                        name=c.name,
                        version=c.version,
                        description=c.description,
                        input_schema_json=c.input_schema_json,
                        output_schema_json=c.output_schema_json,
                        supports_streaming=c.supports_streaming,
                    )
                    for c in app._caps.values()
                ]
                return agent_bridge_pb2.ProbeResponse(
                    agent_name=app.agent_name,
                    agent_version=app.agent_version,
                    auth_mode="none",
                    capabilities=caps,
                )

            def ListCapabilities(self, request, context):
                caps = [
                    agent_bridge_pb2.Capability(
                        name=c.name,
                        version=c.version,
                        description=c.description,
                        input_schema_json=c.input_schema_json,
                        output_schema_json=c.output_schema_json,
                        supports_streaming=c.supports_streaming,
                    )
                    for c in app._caps.values()
                ]
                return agent_bridge_pb2.ListCapabilitiesResponse(capabilities=caps)

            def Invoke(self, request, context):
                t0 = time.time()
                try:
                    result = app._execute(request.task_type, request.payload_json)
                    return agent_bridge_pb2.InvokeResponse(
                        request_id=request.request_id,
                        status="OK",
                        result_json=json.dumps(result, ensure_ascii=False),
                        error_code="",
                        error_message="",
                        latency_ms=int((time.time() - t0) * 1000),
                    )
                except Exception as e:
                    return agent_bridge_pb2.InvokeResponse(
                        request_id=request.request_id,
                        status="ERROR",
                        result_json="{}",
                        error_code="SDK_INVOKE_ERROR",
                        error_message=str(e),
                        latency_ms=int((time.time() - t0) * 1000),
                    )

            def InvokeStream(self, request, context):
                cap = app._caps.get(request.task_type)
                if not cap:
                    yield agent_bridge_pb2.InvokeChunk(
                        request_id=request.request_id,
                        chunk_json="{}",
                        done=True,
                        error_code="SDK_NOT_FOUND",
                        error_message=f"unknown capability: {request.task_type}",
                    )
                    return
                if cap.stream_handler:
                    try:
                        for chunk in cap.stream_handler(request.payload_json):
                            yield agent_bridge_pb2.InvokeChunk(
                                request_id=request.request_id,
                                chunk_json=json.dumps(chunk, ensure_ascii=False),
                                done=False,
                                error_code="",
                                error_message="",
                            )
                    except Exception as e:
                        yield agent_bridge_pb2.InvokeChunk(
                            request_id=request.request_id,
                            chunk_json="{}",
                            done=True,
                            error_code="SDK_STREAM_ERROR",
                            error_message=str(e),
                        )
                        return
                    yield agent_bridge_pb2.InvokeChunk(
                        request_id=request.request_id,
                        chunk_json=json.dumps({"stage": "done"}),
                        done=True,
                        error_code="",
                        error_message="",
                    )
                    return

                resp = self.Invoke(request, context)
                yield agent_bridge_pb2.InvokeChunk(
                    request_id=request.request_id,
                    chunk_json=resp.result_json,
                    done=True,
                    error_code=resp.error_code,
                    error_message=resp.error_message,
                )

            def SubmitTask(self, request, context):
                task_id = str(uuid.uuid4())
                task = _TaskRecord(task_id, request.invoke_request.request_id)
                app._tasks[task_id] = task

                def run():
                    task.status = "RUNNING"
                    task.touch()
                    try:
                        result = app._execute(request.invoke_request.task_type, request.invoke_request.payload_json)
                        task.status = "SUCCEEDED"
                        task.result_json = json.dumps(result, ensure_ascii=False)
                        task.error_code = ""
                        task.error_message = ""
                    except Exception as e:
                        task.status = "FAILED"
                        task.error_code = "SDK_ASYNC_ERROR"
                        task.error_message = str(e)
                    task.touch()

                app._pool.submit(run)
                return agent_bridge_pb2.SubmitTaskResponse(
                    task_id=task_id,
                    request_id=request.invoke_request.request_id,
                    status=agent_bridge_pb2.TASK_STATUS_PENDING,
                )

            def GetTaskStatus(self, request, context):
                task = app._tasks.get(request.task_id)
                if not task:
                    context.abort(grpc.StatusCode.NOT_FOUND, f"task not found: {request.task_id}")

                status_map = {
                    "PENDING": agent_bridge_pb2.TASK_STATUS_PENDING,
                    "RUNNING": agent_bridge_pb2.TASK_STATUS_RUNNING,
                    "SUCCEEDED": agent_bridge_pb2.TASK_STATUS_SUCCEEDED,
                    "FAILED": agent_bridge_pb2.TASK_STATUS_FAILED,
                    "CANCELLED": agent_bridge_pb2.TASK_STATUS_CANCELLED,
                }
                return agent_bridge_pb2.GetTaskStatusResponse(
                    task_id=task.task_id,
                    request_id=task.request_id,
                    status=status_map.get(task.status, agent_bridge_pb2.TASK_STATUS_UNSPECIFIED),
                    result_json=task.result_json,
                    error_code=task.error_code,
                    error_message=task.error_message,
                    created_at_epoch_ms=task.created_at_epoch_ms,
                    updated_at_epoch_ms=task.updated_at_epoch_ms,
                )

        return Servicer(), agent_bridge_pb2_grpc

    def run(self, host: str = "0.0.0.0", port: int = 50051, workers: int = 8):
        servicer, pb2_grpc = self._build_servicer()
        server = grpc.server(ThreadPoolExecutor(max_workers=workers))
        pb2_grpc.add_AgentBridgeServiceServicer_to_server(servicer, server)
        server.add_insecure_port(f"{host}:{port}")
        print(f"AgentBridge SDK server started at {host}:{port}")
        server.start()
        server.wait_for_termination()

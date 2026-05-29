import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections import deque

import grpc
from prometheus_client import Counter, Gauge, Histogram

from app import registry
from app.auth import JwtVerifier, AuthError, extract_bearer
from app.orchestrator import AgentError, route_and_execute
from app.task_store import InMemoryTaskStore, RedisTaskStore, TaskRecord, TaskStatus
from app.validator import validate_payload, ValidationErr

import agent_bridge_pb2
import agent_bridge_pb2_grpc

REQ_COUNTER = Counter("agentbridge_requests_total", "Total requests", ["method", "status"])
LATENCY = Histogram("agentbridge_latency_seconds", "Request latency", ["method"])
TASK_QUEUE = Gauge("agentbridge_task_queue_size", "Async task queue size")


class SimpleRateLimiter:
    def __init__(self, limit: int = 100, window_sec: int = 1) -> None:
        self.limit = limit
        self.window_sec = window_sec
        self._lock = threading.Lock()
        self._events = deque()

    def allow(self) -> bool:
        now = time.time()
        with self._lock:
            while self._events and now - self._events[0] > self.window_sec:
                self._events.popleft()
            if len(self._events) >= self.limit:
                return False
            self._events.append(now)
            return True


class AgentBridgeService(agent_bridge_pb2_grpc.AgentBridgeServiceServicer):
    def __init__(self) -> None:
        self.jwt = JwtVerifier()
        self.limiter = SimpleRateLimiter(limit=int(os.getenv("AGENT_RATE_LIMIT_QPS", "100")), window_sec=1)
        self.task_store = self._build_task_store()
        self.pool = ThreadPoolExecutor(max_workers=int(os.getenv("AGENT_WORKERS", "8")))
        self.task_ttl_sec = int(os.getenv("AGENT_TASK_TTL_SEC", "86400"))
        self.async_retry_max = int(os.getenv("AGENT_ASYNC_RETRY_MAX", "1"))

    def _build_task_store(self):
        store_type = os.getenv("AGENT_TASK_STORE", "memory").strip().lower()
        if store_type == "redis":
            import redis
            client = redis.Redis(
                host=os.getenv("AGENT_REDIS_HOST", "127.0.0.1"),
                port=int(os.getenv("AGENT_REDIS_PORT", "6379")),
                db=int(os.getenv("AGENT_REDIS_DB", "0")),
                username=os.getenv("AGENT_REDIS_USER") or None,
                password=os.getenv("AGENT_REDIS_PASSWORD") or None,
                decode_responses=True,
                socket_timeout=float(os.getenv("AGENT_REDIS_TIMEOUT_SEC", "2")),
            )
            return RedisTaskStore(
                client,
                key_prefix=os.getenv("AGENT_REDIS_KEY_PREFIX", "agentbridge"),
                idem_ttl_sec=int(os.getenv("AGENT_IDEMPOTENCY_TTL_SEC", "86400")),
            )
        return InMemoryTaskStore()

    # ---- fixed chain: trace -> auth -> rate -> audit ----
    def _apply_chain(self, method: str, headers: dict[str, str], task_type: str = "") -> dict:
        trace_id = headers.get("x-trace-id", str(uuid.uuid4()))

        claims = {}
        token = extract_bearer(headers)
        if self.jwt.enabled:
            claims = self.jwt.verify(token)
            allowed = claims.get("capabilities", [])
            if task_type and isinstance(allowed, list) and allowed and task_type not in allowed:
                raise PermissionError(f"capability forbidden: {task_type}")

        if not self.limiter.allow():
            raise RuntimeError("rate limit exceeded")

        print(json.dumps({
            "event": "audit",
            "method": method,
            "task_type": task_type,
            "trace_id": trace_id,
            "sub": claims.get("sub", "anonymous"),
            "ts": int(time.time() * 1000),
        }, ensure_ascii=False))

        return {"trace_id": trace_id, "claims": claims}

    def ProbeAgent(self, request, context):
        t0 = time.time()
        try:
            headers = dict(request.headers)
            self._apply_chain("ProbeAgent", headers)

            caps = [
                agent_bridge_pb2.Capability(
                    name=c.name,
                    version=c.version,
                    description=c.description,
                    input_schema_json=c.input_schema_json,
                    output_schema_json=c.output_schema_json,
                    supports_streaming=c.supports_streaming,
                )
                for c in registry.list_capabilities()
            ]
            REQ_COUNTER.labels("ProbeAgent", "OK").inc()
            return agent_bridge_pb2.ProbeResponse(
                agent_name="python-agent-gateway",
                agent_version="0.2.0",
                auth_mode="jwt" if self.jwt.enabled else "none",
                capabilities=caps,
            )
        except AuthError as e:
            REQ_COUNTER.labels("ProbeAgent", "UNAUTH").inc()
            context.abort(grpc.StatusCode.UNAUTHENTICATED, str(e))
        except PermissionError as e:
            REQ_COUNTER.labels("ProbeAgent", "FORBIDDEN").inc()
            context.abort(grpc.StatusCode.PERMISSION_DENIED, str(e))
        except RuntimeError as e:
            REQ_COUNTER.labels("ProbeAgent", "RATELIMIT").inc()
            context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, str(e))
        finally:
            LATENCY.labels("ProbeAgent").observe(time.time() - t0)

    def ListCapabilities(self, request, context):
        t0 = time.time()
        try:
            headers = dict(request.headers)
            self._apply_chain("ListCapabilities", headers)
            caps = [
                agent_bridge_pb2.Capability(
                    name=c.name,
                    version=c.version,
                    description=c.description,
                    input_schema_json=c.input_schema_json,
                    output_schema_json=c.output_schema_json,
                    supports_streaming=c.supports_streaming,
                )
                for c in registry.list_capabilities()
            ]
            REQ_COUNTER.labels("ListCapabilities", "OK").inc()
            return agent_bridge_pb2.ListCapabilitiesResponse(capabilities=caps)
        except AuthError as e:
            REQ_COUNTER.labels("ListCapabilities", "UNAUTH").inc()
            context.abort(grpc.StatusCode.UNAUTHENTICATED, str(e))
        except PermissionError as e:
            REQ_COUNTER.labels("ListCapabilities", "FORBIDDEN").inc()
            context.abort(grpc.StatusCode.PERMISSION_DENIED, str(e))
        except RuntimeError as e:
            REQ_COUNTER.labels("ListCapabilities", "RATELIMIT").inc()
            context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, str(e))
        finally:
            LATENCY.labels("ListCapabilities").observe(time.time() - t0)

    def Invoke(self, request, context):
        t0 = time.time()
        try:
            headers = dict(request.headers)
            self._apply_chain("Invoke", headers, request.task_type)
            validate_payload(request.task_type, request.payload_json)
            result = route_and_execute(request.task_type, request.payload_json)
            latency_ms = int((time.time() - t0) * 1000)
            REQ_COUNTER.labels("Invoke", "OK").inc()
            return agent_bridge_pb2.InvokeResponse(
                request_id=request.request_id,
                status="OK",
                result_json=json.dumps(result, ensure_ascii=False),
                error_code="",
                error_message="",
                latency_ms=latency_ms,
            )
        except ValidationErr as e:
            REQ_COUNTER.labels("Invoke", "BAD_REQUEST").inc()
            return agent_bridge_pb2.InvokeResponse(
                request_id=request.request_id,
                status="ERROR",
                result_json="{}",
                error_code="AGENT_VALIDATION_ERROR",
                error_message=str(e),
                latency_ms=int((time.time() - t0) * 1000),
            )
        except AgentError as e:
            REQ_COUNTER.labels("Invoke", "ERROR").inc()
            return agent_bridge_pb2.InvokeResponse(
                request_id=request.request_id,
                status="ERROR",
                result_json="{}",
                error_code=e.code,
                error_message=e.message,
                latency_ms=int((time.time() - t0) * 1000),
            )
        except AuthError as e:
            REQ_COUNTER.labels("Invoke", "UNAUTH").inc()
            context.abort(grpc.StatusCode.UNAUTHENTICATED, str(e))
        except PermissionError as e:
            REQ_COUNTER.labels("Invoke", "FORBIDDEN").inc()
            context.abort(grpc.StatusCode.PERMISSION_DENIED, str(e))
        except RuntimeError as e:
            REQ_COUNTER.labels("Invoke", "RATELIMIT").inc()
            context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, str(e))
        finally:
            LATENCY.labels("Invoke").observe(time.time() - t0)

    def InvokeStream(self, request, context):
        t0 = time.time()
        try:
            headers = dict(request.headers)
            trace = self._apply_chain("InvokeStream", headers, request.task_type)["trace_id"]
            validate_payload(request.task_type, request.payload_json)
            yield agent_bridge_pb2.InvokeChunk(
                request_id=request.request_id,
                chunk_json=json.dumps({"stage": "start", "trace_id": trace}),
                done=False,
                error_code="",
                error_message="",
            )
            result = route_and_execute(request.task_type, request.payload_json)
            yield agent_bridge_pb2.InvokeChunk(
                request_id=request.request_id,
                chunk_json=json.dumps({"stage": "result", "data": result}, ensure_ascii=False),
                done=False,
                error_code="",
                error_message="",
            )
            yield agent_bridge_pb2.InvokeChunk(
                request_id=request.request_id,
                chunk_json=json.dumps({"stage": "done"}),
                done=True,
                error_code="",
                error_message="",
            )
            REQ_COUNTER.labels("InvokeStream", "OK").inc()
        except ValidationErr as e:
            REQ_COUNTER.labels("InvokeStream", "BAD_REQUEST").inc()
            yield agent_bridge_pb2.InvokeChunk(
                request_id=request.request_id,
                chunk_json="{}",
                done=True,
                error_code="AGENT_VALIDATION_ERROR",
                error_message=str(e),
            )
        except AgentError as e:
            REQ_COUNTER.labels("InvokeStream", "ERROR").inc()
            yield agent_bridge_pb2.InvokeChunk(
                request_id=request.request_id,
                chunk_json="{}",
                done=True,
                error_code=e.code,
                error_message=e.message,
            )
        except AuthError as e:
            REQ_COUNTER.labels("InvokeStream", "UNAUTH").inc()
            context.abort(grpc.StatusCode.UNAUTHENTICATED, str(e))
        except PermissionError as e:
            REQ_COUNTER.labels("InvokeStream", "FORBIDDEN").inc()
            context.abort(grpc.StatusCode.PERMISSION_DENIED, str(e))
        except RuntimeError as e:
            REQ_COUNTER.labels("InvokeStream", "RATELIMIT").inc()
            context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, str(e))
        finally:
            LATENCY.labels("InvokeStream").observe(time.time() - t0)

    def SubmitTask(self, request, context):
        headers = dict(request.invoke_request.headers)
        self._apply_chain("SubmitTask", headers, request.invoke_request.task_type)
        validate_payload(request.invoke_request.task_type, request.invoke_request.payload_json)

        idem_key = request.invoke_request.idempotency_key
        if idem_key:
            existed = self.task_store.find_by_idempotency(idem_key)
            if existed:
                rec = self.task_store.get(existed)
                return agent_bridge_pb2.SubmitTaskResponse(
                    task_id=rec.task_id,
                    request_id=rec.request_id,
                    status=agent_bridge_pb2.TASK_STATUS_PENDING if rec.status == TaskStatus.PENDING else self._to_proto_status(rec.status),
                )

        task_id = str(uuid.uuid4())
        record = TaskRecord(
            task_id=task_id,
            request_id=request.invoke_request.request_id,
            task_type=request.invoke_request.task_type,
            status=TaskStatus.PENDING,
        )
        self.task_store.create(record)
        if idem_key:
            self.task_store.bind_idempotency(idem_key, task_id)

        self.pool.submit(self._run_task, task_id, request.invoke_request.task_type, request.invoke_request.payload_json)
        TASK_QUEUE.set(self.task_store.pending_count())
        return agent_bridge_pb2.SubmitTaskResponse(
            task_id=task_id,
            request_id=request.invoke_request.request_id,
            status=agent_bridge_pb2.TASK_STATUS_PENDING,
        )

    def _run_task(self, task_id: str, task_type: str, payload_json: str) -> None:
        self.task_store.update(task_id, status=TaskStatus.RUNNING)
        for attempt in range(self.async_retry_max + 1):
            try:
                result = route_and_execute(task_type, payload_json)
                self.task_store.update(
                    task_id,
                    status=TaskStatus.SUCCEEDED,
                    result_json=json.dumps(result, ensure_ascii=False),
                    error_code="",
                    error_message="",
                )
                TASK_QUEUE.set(self.task_store.pending_count())
                return
            except Exception as e:
                if attempt >= self.async_retry_max:
                    self.task_store.update(
                        task_id,
                        status=TaskStatus.FAILED,
                        error_code="AGENT_ASYNC_EXEC_ERROR",
                        error_message=str(e),
                    )
                    TASK_QUEUE.set(self.task_store.pending_count())
                    return
                time.sleep(0.2 * (attempt + 1))

    def GetTaskStatus(self, request, context):
        rec = self.task_store.get(request.task_id)
        if not rec:
            context.abort(grpc.StatusCode.NOT_FOUND, f"task not found: {request.task_id}")
        self.task_store.cleanup(self.task_ttl_sec)
        TASK_QUEUE.set(self.task_store.pending_count())
        return agent_bridge_pb2.GetTaskStatusResponse(
            task_id=rec.task_id,
            request_id=rec.request_id,
            status=self._to_proto_status(rec.status),
            result_json=rec.result_json,
            error_code=rec.error_code,
            error_message=rec.error_message,
            created_at_epoch_ms=rec.created_at_epoch_ms,
            updated_at_epoch_ms=rec.updated_at_epoch_ms,
        )

    def readiness(self) -> tuple[bool, str]:
        return self.task_store.readiness()

    def _to_proto_status(self, status: TaskStatus):
        return {
            TaskStatus.PENDING: agent_bridge_pb2.TASK_STATUS_PENDING,
            TaskStatus.RUNNING: agent_bridge_pb2.TASK_STATUS_RUNNING,
            TaskStatus.SUCCEEDED: agent_bridge_pb2.TASK_STATUS_SUCCEEDED,
            TaskStatus.FAILED: agent_bridge_pb2.TASK_STATUS_FAILED,
            TaskStatus.CANCELLED: agent_bridge_pb2.TASK_STATUS_CANCELLED,
        }.get(status, agent_bridge_pb2.TASK_STATUS_UNSPECIFIED)

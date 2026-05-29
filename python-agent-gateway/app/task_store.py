from dataclasses import dataclass
from enum import Enum
import json
from threading import Lock
import time


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class TaskRecord:
    task_id: str
    request_id: str
    task_type: str
    status: TaskStatus
    result_json: str = "{}"
    error_code: str = ""
    error_message: str = ""
    created_at_epoch_ms: int = 0
    updated_at_epoch_ms: int = 0


class TaskStore:
    def create(self, task: TaskRecord) -> None:
        raise NotImplementedError

    def update(self, task_id: str, **kwargs) -> TaskRecord | None:
        raise NotImplementedError

    def get(self, task_id: str) -> TaskRecord | None:
        raise NotImplementedError

    def find_by_idempotency(self, idempotency_key: str) -> str | None:
        raise NotImplementedError

    def bind_idempotency(self, idempotency_key: str, task_id: str) -> None:
        raise NotImplementedError

    def cleanup(self, ttl_seconds: int) -> int:
        raise NotImplementedError

    def pending_count(self) -> int:
        raise NotImplementedError

    def readiness(self) -> tuple[bool, str]:
        raise NotImplementedError


class InMemoryTaskStore(TaskStore):
    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._idem: dict[str, str] = {}
        self._lock = Lock()

    def create(self, task: TaskRecord) -> None:
        with self._lock:
            now = int(time.time() * 1000)
            task.created_at_epoch_ms = now
            task.updated_at_epoch_ms = now
            self._tasks[task.task_id] = task

    def update(self, task_id: str, **kwargs) -> TaskRecord | None:
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return None
            for k, v in kwargs.items():
                setattr(t, k, v)
            t.updated_at_epoch_ms = int(time.time() * 1000)
            self._tasks[task_id] = t
            return t

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def find_by_idempotency(self, idempotency_key: str) -> str | None:
        with self._lock:
            return self._idem.get(idempotency_key)

    def bind_idempotency(self, idempotency_key: str, task_id: str) -> None:
        with self._lock:
            self._idem[idempotency_key] = task_id

    def cleanup(self, ttl_seconds: int) -> int:
        now_ms = int(time.time() * 1000)
        removed = 0
        with self._lock:
            keys = [k for k, v in self._tasks.items() if (now_ms - v.updated_at_epoch_ms) > ttl_seconds * 1000]
            for k in keys:
                del self._tasks[k]
                removed += 1
        return removed

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for v in self._tasks.values() if v.status in (TaskStatus.PENDING, TaskStatus.RUNNING))

    def readiness(self) -> tuple[bool, str]:
        return True, "inmemory-ok"


class RedisTaskStore(TaskStore):
    def __init__(self, redis_client, key_prefix: str = "agentbridge", idem_ttl_sec: int = 86400) -> None:
        self._redis = redis_client
        self._prefix = key_prefix
        self._idem_ttl_sec = idem_ttl_sec

    def _task_key(self, task_id: str) -> str:
        return f"{self._prefix}:task:{task_id}"

    def _idem_key(self, idem_key: str) -> str:
        return f"{self._prefix}:idem:{idem_key}"

    def _to_dict(self, task: TaskRecord) -> dict:
        return {
            "task_id": task.task_id,
            "request_id": task.request_id,
            "task_type": task.task_type,
            "status": task.status.value,
            "result_json": task.result_json,
            "error_code": task.error_code,
            "error_message": task.error_message,
            "created_at_epoch_ms": task.created_at_epoch_ms,
            "updated_at_epoch_ms": task.updated_at_epoch_ms,
        }

    def _from_dict(self, data: dict | None) -> TaskRecord | None:
        if not data:
            return None
        return TaskRecord(
            task_id=data.get("task_id", ""),
            request_id=data.get("request_id", ""),
            task_type=data.get("task_type", ""),
            status=TaskStatus(data.get("status", "PENDING")),
            result_json=data.get("result_json", "{}"),
            error_code=data.get("error_code", ""),
            error_message=data.get("error_message", ""),
            created_at_epoch_ms=int(data.get("created_at_epoch_ms", 0)),
            updated_at_epoch_ms=int(data.get("updated_at_epoch_ms", 0)),
        )

    def create(self, task: TaskRecord) -> None:
        now = int(time.time() * 1000)
        task.created_at_epoch_ms = now
        task.updated_at_epoch_ms = now
        self._redis.set(self._task_key(task.task_id), json.dumps(self._to_dict(task), ensure_ascii=False))

    def update(self, task_id: str, **kwargs) -> TaskRecord | None:
        rec = self.get(task_id)
        if not rec:
            return None
        for k, v in kwargs.items():
            setattr(rec, k, v)
        rec.updated_at_epoch_ms = int(time.time() * 1000)
        self._redis.set(self._task_key(task_id), json.dumps(self._to_dict(rec), ensure_ascii=False))
        return rec

    def get(self, task_id: str) -> TaskRecord | None:
        raw = self._redis.get(self._task_key(task_id))
        if raw is None:
            return None
        return self._from_dict(json.loads(raw))

    def find_by_idempotency(self, idempotency_key: str) -> str | None:
        raw = self._redis.get(self._idem_key(idempotency_key))
        return raw if raw else None

    def bind_idempotency(self, idempotency_key: str, task_id: str) -> None:
        self._redis.set(self._idem_key(idempotency_key), task_id, ex=self._idem_ttl_sec)

    def cleanup(self, ttl_seconds: int) -> int:
        removed = 0
        now = int(time.time() * 1000)
        cursor = 0
        pattern = f"{self._prefix}:task:*"
        while True:
            cursor, keys = self._redis.scan(cursor=cursor, match=pattern, count=200)
            for k in keys:
                raw = self._redis.get(k)
                if not raw:
                    continue
                data = json.loads(raw)
                updated = int(data.get("updated_at_epoch_ms", 0))
                if now - updated > ttl_seconds * 1000:
                    self._redis.delete(k)
                    removed += 1
            if cursor == 0:
                break
        return removed

    def pending_count(self) -> int:
        count = 0
        cursor = 0
        pattern = f"{self._prefix}:task:*"
        while True:
            cursor, keys = self._redis.scan(cursor=cursor, match=pattern, count=200)
            for k in keys:
                raw = self._redis.get(k)
                if not raw:
                    continue
                data = json.loads(raw)
                if data.get("status") in (TaskStatus.PENDING.value, TaskStatus.RUNNING.value):
                    count += 1
            if cursor == 0:
                break
        return count

    def readiness(self) -> tuple[bool, str]:
        try:
            pong = self._redis.ping()
            return bool(pong), "redis-ok" if pong else "redis-ping-fail"
        except Exception as e:
            return False, f"redis-error:{e}"

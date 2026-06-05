import uuid
import json
import time
import threading
import asyncio
import inspect
from datetime import datetime, date
from typing import Dict, List, Optional, Any, Callable
from functools import wraps
from collections import deque
from contextlib import contextmanager
from sqlalchemy import and_, func

from app import logger, get_db_session
from app.models import OperationLog


class OperationLogger:
    _instance = None
    _lock = threading.Lock()
    _buffer: deque = deque()
    _buffer_size = 100
    _flush_interval = 5
    _flush_lock = threading.Lock()
    _running = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._start_flush_thread()
        return cls._instance

    def _start_flush_thread(self):
        if not self._running:
            self._running = True
            t = threading.Thread(target=self._flush_loop, daemon=True)
            t.start()

    def _flush_loop(self):
        while True:
            try:
                time.sleep(self._flush_interval)
                self._flush_buffer()
            except Exception as e:
                logger.error(f"日志刷新线程异常: {e}")

    def _flush_buffer(self):
        with self._flush_lock:
            if not self._buffer:
                return
            logs_to_flush = list(self._buffer)
            self._buffer.clear()

        db = get_db_session()
        try:
            for log_data in logs_to_flush:
                log = OperationLog(**log_data)
                db.add(log)
            db.commit()
        except Exception as e:
            logger.error(f"批量写入日志失败: {e}")
            db.rollback()
        finally:
            db.close()

    def log(
        self,
        user_id: str = "system",
        user_name: str = "系统",
        role: str = "system",
        module: str = "",
        action: str = "",
        target_type: str = "",
        target_id: str = "",
        description: str = "",
        request_ip: str = "",
        user_agent: str = "",
        before_data: Optional[Dict] = None,
        after_data: Optional[Dict] = None,
        status: str = "success",
        error_msg: str = "",
    ):
        log_data = {
            "log_id": f"LOG_{uuid.uuid4().hex[:16]}",
            "user_id": user_id,
            "user_name": user_name,
            "role": role,
            "module": module,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "description": description,
            "request_ip": request_ip,
            "user_agent": user_agent,
            "before_data": before_data,
            "after_data": after_data,
            "status": status,
            "error_msg": error_msg,
            "created_at": datetime.now(),
        }
        with self._lock:
            self._buffer.append(log_data)
            if len(self._buffer) >= self._buffer_size:
                threading.Thread(target=self._flush_buffer, daemon=True).start()

    def query_logs(
        self,
        user_id: Optional[str] = None,
        module: Optional[str] = None,
        action: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict:
        self._flush_buffer()
        db = get_db_session()
        try:
            query = db.query(OperationLog)

            if user_id:
                query = query.filter(OperationLog.user_id == user_id)
            if module:
                query = query.filter(OperationLog.module == module)
            if action:
                query = query.filter(OperationLog.action == action)
            if target_type:
                query = query.filter(OperationLog.target_type == target_type)
            if target_id:
                query = query.filter(OperationLog.target_id == target_id)
            if status:
                query = query.filter(OperationLog.status == status)
            if start_time:
                query = query.filter(OperationLog.created_at >= start_time)
            if end_time:
                query = query.filter(OperationLog.created_at <= end_time)

            total = query.count()
            logs = query.order_by(OperationLog.created_at.desc()).offset(offset).limit(limit).all()

            items = [
                {
                    "log_id": log.log_id,
                    "user_id": log.user_id,
                    "user_name": log.user_name,
                    "role": log.role,
                    "module": log.module,
                    "action": log.action,
                    "target_type": log.target_type,
                    "target_id": log.target_id,
                    "description": log.description,
                    "request_ip": log.request_ip,
                    "status": log.status,
                    "error_msg": log.error_msg,
                    "created_at": log.created_at,
                }
                for log in logs
            ]

            return {"total": total, "items": items, "limit": limit, "offset": offset}
        finally:
            db.close()

    def get_stats(self, target_date: Optional[date] = None) -> Dict:
        self._flush_buffer()
        db = get_db_session()
        try:
            if not target_date:
                target_date = date.today()
            start = datetime.combine(target_date, datetime.min.time())
            end = datetime.combine(target_date, datetime.max.time())

            total_ops = db.query(OperationLog).filter(
                and_(OperationLog.created_at >= start, OperationLog.created_at <= end)
            ).count()

            by_module = (
                db.query(OperationLog.module, func.count(OperationLog.id))
                .filter(and_(OperationLog.created_at >= start, OperationLog.created_at <= end))
                .group_by(OperationLog.module)
                .all()
            )

            by_status = (
                db.query(OperationLog.status, func.count(OperationLog.id))
                .filter(and_(OperationLog.created_at >= start, OperationLog.created_at <= end))
                .group_by(OperationLog.status)
                .all()
            )

            return {
                "date": str(target_date),
                "total_operations": total_ops,
                "by_module": {m: c for m, c in by_module},
                "by_status": {s: c for s, c in by_status},
            }
        finally:
            db.close()

    def force_flush(self):
        self._flush_buffer()


operation_logger = OperationLogger()


def log_operation(
    module: str,
    action: str,
    target_type: str = "",
    description: str = "",
):
    def decorator(func: Callable) -> Callable:
        is_async = inspect.iscoroutinefunction(func)

        if is_async:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                operation_logger.log(
                    module=module,
                    action=action,
                    target_type=target_type,
                    description=f"{description} - 开始执行",
                )
                try:
                    result = await func(*args, **kwargs)
                    operation_logger.log(
                        module=module,
                        action=action,
                        target_type=target_type,
                        description=f"{description} - 执行成功 (耗时{(time.time()-start_time):.3f}s)",
                        status="success",
                    )
                    return result
                except Exception as e:
                    operation_logger.log(
                        module=module,
                        action=action,
                        target_type=target_type,
                        description=f"{description} - 执行失败",
                        status="failed",
                        error_msg=str(e),
                    )
                    raise
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()
                operation_logger.log(
                    module=module,
                    action=action,
                    target_type=target_type,
                    description=f"{description} - 开始执行",
                )
                try:
                    result = func(*args, **kwargs)
                    operation_logger.log(
                        module=module,
                        action=action,
                        target_type=target_type,
                        description=f"{description} - 执行成功 (耗时{(time.time()-start_time):.3f}s)",
                        status="success",
                    )
                    return result
                except Exception as e:
                    operation_logger.log(
                        module=module,
                        action=action,
                        target_type=target_type,
                        description=f"{description} - 执行失败",
                        status="failed",
                        error_msg=str(e),
                    )
                    raise
            return sync_wrapper
    return decorator


class ConcurrencyLimiter:
    def __init__(self, max_concurrent: int = 100):
        self.max_concurrent = max_concurrent
        self._semaphore = threading.Semaphore(max_concurrent)
        self._active = 0
        self._lock = threading.Lock()

    @contextmanager
    def acquire(self, timeout: float = 30.0):
        acquired = self._semaphore.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError(f"并发请求数超限，等待{timeout}秒后仍未获取锁")
        try:
            with self._lock:
                self._active += 1
            yield
        finally:
            with self._lock:
                self._active -= 1
            self._semaphore.release()

    @property
    def active_count(self):
        with self._lock:
            return self._active


class RateLimiter:
    def __init__(self, max_requests: int = 1000, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: deque = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.time()
        with self._lock:
            while self._requests and self._requests[0] < now - self.window_seconds:
                self._requests.popleft()
            if len(self._requests) >= self.max_requests:
                return False
            self._requests.append(now)
            return True

    @contextmanager
    def limit(self):
        if not self.allow():
            raise RuntimeError(f"请求频率超限: {self.max_requests}/{self.window_seconds}s")
        yield


concurrency_limiter = ConcurrencyLimiter(max_concurrent=500)
rate_limiter = RateLimiter(max_requests=5000, window_seconds=60)


class BatchProcessor:
    def __init__(self, batch_size: int = 1000, num_workers: int = 4):
        self.batch_size = batch_size
        self.num_workers = num_workers

    def process(self, items: List[Any], processor: Callable[[Any], Any]) -> List[Any]:
        results = []
        lock = threading.Lock()

        def worker(batch):
            batch_results = []
            for item in batch:
                try:
                    batch_results.append(processor(item))
                except Exception as e:
                    logger.error(f"批量处理异常: {e}")
            with lock:
                results.extend(batch_results)

        threads = []
        for i in range(0, len(items), self.batch_size):
            batch = items[i : i + self.batch_size]
            t = threading.Thread(target=worker, args=(batch,), daemon=True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        return results

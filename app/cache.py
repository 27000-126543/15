import json
import time
import threading
from functools import wraps
from typing import Any, Optional, Dict, Callable
from datetime import datetime, date
from config import settings

try:
    import redis as redis_lib
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from app import logger


class CacheLayer:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self.enabled = settings.REDIS_ENABLED and REDIS_AVAILABLE
        self._client: Optional[redis_lib.Redis] = None
        self._local_cache: Dict[str, tuple] = {}
        self._local_lock = threading.Lock()

        if self.enabled:
            try:
                redis_kwargs = {
                    "host": settings.REDIS_HOST,
                    "port": settings.REDIS_PORT,
                    "db": settings.REDIS_DB,
                    "decode_responses": True,
                    "socket_connect_timeout": 5,
                    "socket_timeout": 10,
                }
                if settings.REDIS_PASSWORD:
                    redis_kwargs["password"] = settings.REDIS_PASSWORD
                self._client = redis_lib.Redis(**redis_kwargs)
                self._client.ping()
                logger.info(
                    f"Redis 缓存已连接: {settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
                )
            except Exception as e:
                logger.warning(f"Redis 连接失败，降级为本地内存缓存: {e}")
                self.enabled = False
                self._client = None
        else:
            if not REDIS_AVAILABLE:
                logger.info("Redis 包未安装，使用本地内存缓存")
            else:
                logger.info("Redis 未启用 (REDIS_ENABLED=false)，使用本地内存缓存")

    def _json_default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return str(obj)

    def _serialize(self, value: Any) -> str:
        try:
            return json.dumps(value, default=self._json_default, ensure_ascii=False)
        except Exception:
            return json.dumps(str(value), ensure_ascii=False)

    def _deserialize(self, raw: str) -> Any:
        try:
            return json.loads(raw)
        except Exception:
            return raw

    def get(self, key: str) -> Optional[Any]:
        full_key = f"live_ops:{key}"
        if self.enabled and self._client:
            try:
                raw = self._client.get(full_key)
                if raw is not None:
                    return self._deserialize(raw)
                return None
            except Exception as e:
                logger.warning(f"Redis get 失败，回退本地缓存: {e}")
        with self._local_lock:
            entry = self._local_cache.get(full_key)
            if entry:
                value, expire_at = entry
                if expire_at == 0 or time.time() < expire_at:
                    return value
                del self._local_cache[full_key]
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        if ttl is None:
            ttl = settings.REDIS_CACHE_TTL
        full_key = f"live_ops:{key}"
        serialized = self._serialize(value)

        if self.enabled and self._client:
            try:
                if ttl > 0:
                    self._client.setex(full_key, ttl, serialized)
                else:
                    self._client.set(full_key, serialized)
                return
            except Exception as e:
                logger.warning(f"Redis set 失败，回退本地缓存: {e}")

        with self._local_lock:
            expire_at = time.time() + ttl if ttl > 0 else 0
            self._local_cache[full_key] = (value, expire_at)
            if len(self._local_cache) > 10000:
                self._clean_local_cache()

    def delete(self, key: str) -> None:
        full_key = f"live_ops:{key}"
        if self.enabled and self._client:
            try:
                self._client.delete(full_key)
            except Exception as e:
                logger.warning(f"Redis delete 失败: {e}")
        with self._local_lock:
            self._local_cache.pop(full_key, None)

    def delete_pattern(self, pattern: str) -> None:
        full_pattern = f"live_ops:{pattern}"
        if self.enabled and self._client:
            try:
                keys = list(self._client.scan_iter(match=full_pattern))
                if keys:
                    self._client.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis delete_pattern 失败: {e}")
        with self._local_lock:
            to_delete = [k for k in self._local_cache if k.startswith(full_pattern.replace("*", ""))]
            for k in to_delete:
                del self._local_cache[k]

    def _clean_local_cache(self):
        now = time.time()
        expired = [k for k, (_, exp) in self._local_cache.items() if exp > 0 and exp < now]
        for k in expired:
            del self._local_cache[k]
        while len(self._local_cache) > 8000:
            oldest_key = next(iter(self._local_cache))
            del self._local_cache[oldest_key]

    def set_realtime(self, session_id: str, data: Dict) -> None:
        self.set(f"realtime:{session_id}", data, ttl=settings.REDIS_REALTIME_TTL)

    def get_realtime(self, session_id: str) -> Optional[Dict]:
        return self.get(f"realtime:{session_id}")

    def get_stats(self) -> Dict:
        stats = {
            "enabled": self.enabled,
            "redis_connected": self._client is not None,
            "local_cache_size": len(self._local_cache),
            "default_cache_ttl": settings.REDIS_CACHE_TTL,
            "realtime_ttl": settings.REDIS_REALTIME_TTL,
        }
        if self.enabled and self._client:
            try:
                info = self._client.info()
                stats["redis_used_memory"] = info.get("used_memory_human", "N/A")
                stats["redis_connected_clients"] = info.get("connected_clients", 0)
                stats["redis_total_commands"] = info.get("total_commands_processed", 0)
            except Exception:
                pass
        return stats


def cached(key_pattern: str, ttl: Optional[int] = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache = cache_layer
            key_parts = [key_pattern]
            for a in args:
                if isinstance(a, (str, int, float, bool)):
                    key_parts.append(str(a))
            for k, v in sorted(kwargs.items()):
                if isinstance(v, (str, int, float, bool)):
                    key_parts.append(f"{k}={v}")
            cache_key = ":".join(key_parts)

            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result

            result = func(*args, **kwargs)
            try:
                cache.set(cache_key, result, ttl=ttl)
            except Exception:
                pass
            return result

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            cache = cache_layer
            key_parts = [key_pattern]
            for a in args:
                if isinstance(a, (str, int, float, bool)):
                    key_parts.append(str(a))
            for k, v in sorted(kwargs.items()):
                if isinstance(v, (str, int, float, bool)):
                    key_parts.append(f"{k}={v}")
            cache_key = ":".join(key_parts)

            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result

            result = await func(*args, **kwargs)
            try:
                cache.set(cache_key, result, ttl=ttl)
            except Exception:
                pass
            return result

        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


cache_layer = CacheLayer()

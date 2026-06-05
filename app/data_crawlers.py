import uuid
import random
import time
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Tuple
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app import logger, get_db_session
from app.models import (
    LiveSession, RealtimeDataPoint, LiveProduct, Order, Anchor, Product
)
from app.cache import cache_layer
from config import settings, PlatformAPIConfig

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    logger.warning("requests 库未安装，只能使用mock数据源")
    REQUESTS_AVAILABLE = False


class APIRequestError(Exception):
    pass


class BasePlatformCrawler:
    platform_name: str = "base"
    api_endpoints: Dict[str, str] = {
        "sessions": "/live/sessions",
        "realtime": "/live/realtime",
        "orders": "/live/orders",
    }

    def __init__(self):
        self.session = None
        self.api_config: PlatformAPIConfig = settings.get_platform_config(self.platform_name)
        self._http_session = None
        self._last_request_ts = 0.0
        self._min_interval = 0.1

        if self.api_config.enabled and REQUESTS_AVAILABLE:
            self._init_http_session()
            logger.info(
                f"[{self.platform_name}] 真实API模式已启用: "
                f"base_url={self.api_config.base_url}, "
                f"timeout={self.api_config.timeout}s"
            )
        elif self.api_config.enabled and not REQUESTS_AVAILABLE:
            logger.warning(
                f"[{self.platform_name}] requests库不可用，"
                f"尽管API已启用，但将降级为mock模式"
            )
        else:
            logger.info(f"[{self.platform_name}] Mock模式 (API未启用)")

    def _init_http_session(self):
        self._http_session = requests.Session()
        if self.api_config.api_token:
            self._http_session.headers.update({
                "Authorization": f"Bearer {self.api_config.api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "LiveOpsPlatformCrawler/1.0",
            })
        else:
            self._http_session.headers.update({
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "LiveOpsPlatformCrawler/1.0",
            })

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_ts
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_ts = time.time()

    def _http_get(
        self,
        endpoint: str,
        params: Optional[Dict] = None,
        cache_key: Optional[str] = None,
        cache_ttl: Optional[int] = None,
    ) -> Tuple[Optional[Any], Optional[str]]:
        if not (self.api_config.enabled and REQUESTS_AVAILABLE and self._http_session):
            return None, "api_disabled"

        if cache_key:
            cached = cache_layer.get(cache_key)
            if cached is not None:
                return cached, None

        self._rate_limit()
        url = f"{self.api_config.base_url.rstrip('/')}/{endpoint.lstrip('/')}"

        for attempt in range(self.api_config.retry_count):
            try:
                resp = self._http_session.get(
                    url,
                    params=params or {},
                    timeout=self.api_config.timeout,
                )
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        if cache_key:
                            cache_layer.set(cache_key, data, ttl=cache_ttl)
                        return data, None
                    except ValueError:
                        return None, f"invalid_json: {resp.text[:200]}"
                elif resp.status_code in (429, 500, 502, 503, 504):
                    delay = self.api_config.retry_delay * (2 ** attempt)
                    logger.warning(
                        f"[{self.platform_name}] API返回{resp.status_code}, "
                        f"{delay}s后重试 (attempt {attempt+1}/{self.api_config.retry_count})"
                    )
                    time.sleep(delay)
                    continue
                else:
                    return None, f"http_{resp.status_code}: {resp.text[:200]}"
            except requests.Timeout:
                delay = self.api_config.retry_delay * (2 ** attempt)
                logger.warning(
                    f"[{self.platform_name}] API超时, {delay}s后重试 "
                    f"(attempt {attempt+1}/{self.api_config.retry_count})"
                )
                time.sleep(delay)
                continue
            except requests.RequestException as e:
                delay = self.api_config.retry_delay * (2 ** attempt)
                logger.warning(
                    f"[{self.platform_name}] API请求异常: {e}, {delay}s后重试 "
                    f"(attempt {attempt+1}/{self.api_config.retry_count})"
                )
                time.sleep(delay)
                continue

        return None, "max_retries_exceeded"

    def _to_datetime(self, d) -> datetime:
        if isinstance(d, datetime):
            return d
        if isinstance(d, date):
            return datetime.combine(d, datetime.min.time())
        if isinstance(d, str):
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(d, fmt)
                except ValueError:
                    continue
        return datetime.now()

    def generate_session_id(self) -> str:
        return f"{self.platform_name.upper()}_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(APIRequestError),
    )
    def fetch_live_sessions(self, target_date: Optional[date] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(APIRequestError),
    )
    def fetch_realtime_data(self, session_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(APIRequestError),
    )
    def fetch_orders(self, session_id: str, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError


class DouyinCrawler(BasePlatformCrawler):
    platform_name = "抖音"
    api_endpoints = {
        "sessions": "/openapi/live/v1/session/list",
        "realtime": "/openapi/live/v1/session/realtime",
        "orders": "/openapi/live/v1/order/list",
    }

    def _parse_api_sessions(self, data: Any) -> List[Dict]:
        if not data or not isinstance(data, (dict, list)):
            return []
        items = data
        if isinstance(data, dict):
            d = data.get("data", data)
            if isinstance(d, dict):
                items = (d.get("sessions")
                         or d.get("list")
                         or d.get("items")
                         or d.get("records")
                         or [])
            else:
                items = d
        if not isinstance(items, list):
            return []
        result = []
        for item in items:
            try:
                result.append({
                    "session_id": str(item.get("session_id") or self.generate_session_id()),
                    "anchor_id": str(item.get("anchor_id") or f"DY_{random.randint(1000, 9999)}"),
                    "anchor_name": str(item.get("anchor_name") or f"抖音主播"),
                    "platform": self.platform_name,
                    "title": str(item.get("title") or "抖音直播间"),
                    "start_time": self._to_datetime(item.get("start_time")),
                    "estimated_traffic": int(item.get("estimated_traffic") or random.randint(50000, 500000)),
                    "estimated_subsidy": float(item.get("estimated_subsidy") or random.uniform(5000, 50000)),
                    "estimated_gmv": float(item.get("estimated_gmv") or random.uniform(100000, 1000000)),
                    "target_gmv": float(item.get("target_gmv") or random.uniform(200000, 2000000)),
                })
            except Exception as e:
                logger.debug(f"[{self.platform_name}] 解析场次数据异常: {e}")
        return result

    def _mock_sessions(self, target_date) -> List[Dict]:
        sessions = []
        for i in range(random.randint(2, 5)):
            start_time = self._to_datetime(target_date)
            start_time = start_time.replace(hour=random.randint(18, 22), minute=random.randint(0, 59))
            sessions.append({
                "session_id": self.generate_session_id(),
                "anchor_id": f"DY_{random.randint(1000, 9999)}",
                "anchor_name": f"抖音主播{i+1}",
                "platform": self.platform_name,
                "title": f"直播间{i+1} - 好物推荐",
                "start_time": start_time,
                "estimated_traffic": random.randint(50000, 500000),
                "estimated_subsidy": random.uniform(5000, 50000),
                "estimated_gmv": random.uniform(100000, 1000000),
                "target_gmv": random.uniform(200000, 2000000),
            })
        return sessions

    def fetch_live_sessions(self, target_date=None):
        if self.api_config.enabled and REQUESTS_AVAILABLE:
            date_str = target_date.strftime("%Y-%m-%d") if target_date else date.today().strftime("%Y-%m-%d")
            cache_key = f"douyin:sessions:{date_str}"
            data, err = self._http_get(
                self.api_endpoints["sessions"],
                params={"date": date_str, "limit": 50},
                cache_key=cache_key,
                cache_ttl=300,
            )
            parsed = self._parse_api_sessions(data) if data else []
            if parsed:
                logger.info(f"[{self.platform_name}] 从API获取 {len(parsed)} 场直播")
                return parsed
            if err != "api_disabled":
                logger.warning(f"[{self.platform_name}] API获取直播场次失败: {err}, 回退mock")
        return self._mock_sessions(target_date)

    def _parse_api_realtime(self, data: Any) -> Dict:
        if not data or not isinstance(data, dict):
            return {}
        d = data.get("data", data)
        return {
            "viewer_count": int(d.get("viewer_count") or 0),
            "new_viewers": int(d.get("new_viewers") or 0),
            "interaction_count": int(d.get("interaction_count") or 0),
            "click_count": int(d.get("click_count") or 0),
            "order_count": int(d.get("order_count") or 0),
            "gmv": float(d.get("gmv") or 0),
        }

    def _mock_realtime(self) -> Dict:
        return {
            "viewer_count": random.randint(1000, 50000),
            "new_viewers": random.randint(100, 5000),
            "interaction_count": random.randint(50, 2000),
            "click_count": random.randint(20, 1000),
            "order_count": random.randint(5, 200),
            "gmv": random.uniform(500, 50000),
        }

    def fetch_realtime_data(self, session_id: str) -> Dict:
        if self.api_config.enabled and REQUESTS_AVAILABLE:
            data, err = self._http_get(
                self.api_endpoints["realtime"],
                params={"session_id": session_id},
                cache_key=f"douyin:realtime:{session_id}",
                cache_ttl=30,
            )
            parsed = self._parse_api_realtime(data)
            if parsed:
                return parsed
            if err != "api_disabled":
                logger.debug(f"[{self.platform_name}] API获取实时数据失败: {err}, 回退mock")
        return self._mock_realtime()

    def _parse_api_orders(self, data: Any, session_id: str) -> List[Dict]:
        if not data or not isinstance(data, (dict, list)):
            return []
        items = data
        if isinstance(data, dict):
            d = data.get("data", data)
            if isinstance(d, dict):
                items = (d.get("orders")
                         or d.get("list")
                         or d.get("items")
                         or d.get("records")
                         or [])
            else:
                items = d
        if not isinstance(items, list):
            return []
        result = []
        for item in items:
            try:
                qty = int(item.get("quantity") or 1)
                unit_price = float(item.get("unit_price") or item.get("price") or 99.0)
                paid = float(item.get("paid_amount") or item.get("total_amount") or (qty * unit_price))
                result.append({
                    "order_id": str(item.get("order_id") or f"ORD_{uuid.uuid4().hex[:12]}"),
                    "session_id": session_id,
                    "product_sku": str(item.get("product_sku") or item.get("sku") or f"SKU{random.randint(1000, 9999)}"),
                    "product_name": str(item.get("product_name") or item.get("name") or "商品"),
                    "quantity": qty,
                    "unit_price": unit_price,
                    "paid_amount": paid,
                    "buyer_nick": str(item.get("buyer_nick") or "买家"),
                    "order_time": self._to_datetime(item.get("order_time")),
                    "status": str(item.get("status") or "paid"),
                })
            except Exception as e:
                logger.debug(f"[{self.platform_name}] 解析订单异常: {e}")
        return result

    def _mock_orders(self, session_id: str) -> List[Dict]:
        orders = []
        for _ in range(random.randint(10, 100)):
            sku = f"SKU{random.randint(1000, 9999)}"
            qty = random.randint(1, 5)
            price = random.uniform(29.9, 999.9)
            orders.append({
                "order_id": f"ORD_{uuid.uuid4().hex[:12]}",
                "session_id": session_id,
                "product_sku": sku,
                "quantity": qty,
                "unit_price": price,
                "total_amount": round(qty * price, 2),
                "discount_amount": round(qty * price * random.uniform(0, 0.15), 2),
            })
        return orders

    def fetch_orders(self, session_id: str, since=None) -> List[Dict]:
        if self.api_config.enabled and REQUESTS_AVAILABLE:
            params = {"session_id": session_id, "limit": 500}
            if since:
                params["since"] = since.strftime("%Y-%m-%dT%H:%M:%S")
            data, err = self._http_get(
                self.api_endpoints["orders"],
                params=params,
                cache_key=f"douyin:orders:{session_id}",
                cache_ttl=60,
            )
            parsed = self._parse_api_orders(data, session_id) if data else []
            if parsed:
                logger.info(f"[{self.platform_name}] 从API获取 {len(parsed)} 条订单")
                return parsed
            if err != "api_disabled":
                logger.debug(f"[{self.platform_name}] API获取订单失败: {err}, 回退mock")
        return self._mock_orders(session_id)


class _GenericPlatformCrawler(BasePlatformCrawler):
    platform_name = "base"
    _cfg = {}

    def _parse_api_sessions(self, data: Any) -> List[Dict]:
        if not data or not isinstance(data, (dict, list)):
            return []
        items = data
        if isinstance(data, dict):
            d = data.get("data", data)
            if isinstance(d, dict):
                items = (d.get("sessions")
                         or d.get("list")
                         or d.get("items")
                         or d.get("records")
                         or [])
            else:
                items = d
        if not isinstance(items, list):
            return []
        result = []
        for item in items:
            try:
                result.append({
                    "session_id": str(item.get("session_id") or self.generate_session_id()),
                    "anchor_id": str(item.get("anchor_id") or f"{self._cfg.get('id_prefix')}_{random.randint(1000, 9999)}"),
                    "anchor_name": str(item.get("anchor_name") or self._cfg.get("anchor_prefix", "") + "主播"),
                    "platform": self.platform_name,
                    "title": str(item.get("title") or self.platform_name + "直播间"),
                    "start_time": self._to_datetime(item.get("start_time")),
                    "estimated_traffic": int(item.get("estimated_traffic") or random.randint(*self._cfg.get("traffic_range", (10000, 100000)))),
                    "estimated_subsidy": float(item.get("estimated_subsidy") or random.uniform(*self._cfg.get("subsidy_range", (1000, 10000)))),
                    "estimated_gmv": float(item.get("estimated_gmv") or random.uniform(*self._cfg.get("gmv_range", (50000, 500000)))),
                    "target_gmv": float(item.get("target_gmv") or random.uniform(*self._cfg.get("target_range", (100000, 1000000)))),
                })
            except Exception as e:
                logger.debug(f"[{self.platform_name}] 解析场次异常: {e}")
        return result

    def _mock_sessions(self, target_date) -> List[Dict]:
        cfg = self._cfg
        sessions = []
        n_min, n_max = cfg.get("sessions_range", (1, 3))
        for i in range(random.randint(n_min, n_max)):
            start_time = self._to_datetime(target_date)
            h_min, h_max = cfg.get("hour_range", (19, 22))
            start_time = start_time.replace(
                hour=random.randint(h_min, h_max),
                minute=random.randint(0, 59),
            )
            sessions.append({
                "session_id": self.generate_session_id(),
                "anchor_id": f"{cfg['id_prefix']}_{random.randint(1000, 9999)}",
                "anchor_name": f"{cfg['anchor_prefix']}{i+1}",
                "platform": self.platform_name,
                "title": f"{cfg['title_prefix']}{i+1}",
                "start_time": start_time,
                "estimated_traffic": random.randint(*cfg.get("traffic_range", (10000, 100000))),
                "estimated_subsidy": random.uniform(*cfg.get("subsidy_range", (1000, 10000))),
                "estimated_gmv": random.uniform(*cfg.get("gmv_range", (50000, 500000))),
                "target_gmv": random.uniform(*cfg.get("target_range", (100000, 1000000))),
            })
        return sessions

    def fetch_live_sessions(self, target_date=None):
        if self.api_config.enabled and REQUESTS_AVAILABLE:
            date_str = target_date.strftime("%Y-%m-%d") if target_date else date.today().strftime("%Y-%m-%d")
            cache_key = f"{self.platform_name}:sessions:{date_str}"
            data, err = self._http_get(
                self.api_endpoints["sessions"],
                params={"date": date_str, "limit": 50},
                cache_key=cache_key,
                cache_ttl=300,
            )
            parsed = self._parse_api_sessions(data) if data else []
            if parsed:
                logger.info(f"[{self.platform_name}] 从API获取 {len(parsed)} 场直播")
                return parsed
            if err != "api_disabled":
                logger.warning(f"[{self.platform_name}] API获取失败: {err}, 回退mock")
        return self._mock_sessions(target_date)

    def _parse_api_realtime(self, data: Any) -> Dict:
        if not data or not isinstance(data, dict):
            return {}
        d = data.get("data", data)
        return {
            "viewer_count": int(d.get("viewer_count") or 0),
            "new_viewers": int(d.get("new_viewers") or 0),
            "interaction_count": int(d.get("interaction_count") or 0),
            "click_count": int(d.get("click_count") or 0),
            "order_count": int(d.get("order_count") or 0),
            "gmv": float(d.get("gmv") or 0),
        }

    def _mock_realtime(self) -> Dict:
        cfg = self._cfg
        return {
            "viewer_count": random.randint(*cfg.get("viewer_range", (100, 50000))),
            "new_viewers": random.randint(*cfg.get("new_viewer_range", (10, 5000))),
            "interaction_count": random.randint(*cfg.get("interaction_range", (20, 2000))),
            "click_count": random.randint(*cfg.get("click_range", (5, 1000))),
            "order_count": random.randint(*cfg.get("order_range", (1, 200))),
            "gmv": random.uniform(*cfg.get("gmv_rt_range", (100, 50000))),
        }

    def fetch_realtime_data(self, session_id: str) -> Dict:
        if self.api_config.enabled and REQUESTS_AVAILABLE:
            data, err = self._http_get(
                self.api_endpoints["realtime"],
                params={"session_id": session_id},
                cache_key=f"{self.platform_name}:realtime:{session_id}",
                cache_ttl=30,
            )
            parsed = self._parse_api_realtime(data)
            if parsed:
                return parsed
        return self._mock_realtime()

    def _parse_api_orders(self, data: Any, session_id: str) -> List[Dict]:
        if not data or not isinstance(data, (dict, list)):
            return []
        items = data
        if isinstance(data, dict):
            d = data.get("data", data)
            if isinstance(d, dict):
                items = (d.get("orders")
                         or d.get("list")
                         or d.get("items")
                         or d.get("records")
                         or [])
            else:
                items = d
        if not isinstance(items, list):
            return []
        result = []
        for item in items:
            try:
                qty = int(item.get("quantity") or 1)
                price = float(item.get("unit_price") or item.get("price")
                              or random.uniform(*self._cfg.get("price_range", (29.9, 999.9))))
                paid = float(item.get("paid_amount") or item.get("total_amount") or round(qty * price, 2))
                result.append({
                    "order_id": str(item.get("order_id") or f"ORD_{uuid.uuid4().hex[:12]}"),
                    "session_id": session_id,
                    "product_sku": str(item.get("product_sku") or item.get("sku")
                                       or f"SKU{random.randint(1000, 9999)}"),
                    "product_name": str(item.get("product_name") or item.get("name") or "商品"),
                    "quantity": qty,
                    "unit_price": price,
                    "paid_amount": paid,
                    "buyer_nick": str(item.get("buyer_nick") or "买家"),
                    "order_time": self._to_datetime(item.get("order_time")),
                    "status": str(item.get("status") or "paid"),
                })
            except Exception as e:
                logger.debug(f"[{self.platform_name}] 解析订单异常: {e}")
        return result

    def _mock_orders(self, session_id: str) -> List[Dict]:
        cfg = self._cfg
        orders = []
        n_min, n_max = cfg.get("order_count_range", (5, 80))
        for _ in range(random.randint(n_min, n_max)):
            sku = f"SKU{random.randint(1000, 9999)}"
            q_min, q_max = cfg.get("qty_range", (1, 5))
            qty = random.randint(q_min, q_max)
            p_min, p_max = cfg.get("price_range", (29.9, 999.9))
            price = random.uniform(p_min, p_max)
            orders.append({
                "order_id": f"ORD_{uuid.uuid4().hex[:12]}",
                "session_id": session_id,
                "product_sku": sku,
                "quantity": qty,
                "unit_price": price,
                "total_amount": round(qty * price, 2),
                "discount_amount": round(qty * price * random.uniform(0, cfg.get("max_discount", 0.15)), 2),
            })
        return orders

    def fetch_orders(self, session_id: str, since=None) -> List[Dict]:
        if self.api_config.enabled and REQUESTS_AVAILABLE:
            params = {"session_id": session_id, "limit": 500}
            if since:
                params["since"] = since.strftime("%Y-%m-%dT%H:%M:%S")
            data, err = self._http_get(
                self.api_endpoints["orders"],
                params=params,
                cache_key=f"{self.platform_name}:orders:{session_id}",
                cache_ttl=60,
            )
            parsed = self._parse_api_orders(data, session_id) if data else []
            if parsed:
                logger.info(f"[{self.platform_name}] 从API获取 {len(parsed)} 条订单")
                return parsed
        return self._mock_orders(session_id)


class KuaishouCrawler(_GenericPlatformCrawler):
    platform_name = "快手"
    api_endpoints = {
        "sessions": "/openapi/live/v1/session/list",
        "realtime": "/openapi/live/v1/session/realtime",
        "orders": "/openapi/live/v1/order/list",
    }
    _cfg = {
        "id_prefix": "KS",
        "anchor_prefix": "快手主播",
        "title_prefix": "老铁直播间",
        "sessions_range": (1, 4),
        "hour_range": (19, 23),
        "traffic_range": (30000, 300000),
        "subsidy_range": (3000, 30000),
        "gmv_range": (80000, 800000),
        "target_range": (150000, 1500000),
        "viewer_range": (800, 40000),
        "new_viewer_range": (80, 4000),
        "interaction_range": (40, 1500),
        "click_range": (15, 800),
        "order_range": (3, 150),
        "gmv_rt_range": (400, 40000),
        "order_count_range": (8, 80),
        "qty_range": (1, 5),
        "price_range": (19.9, 899.9),
        "max_discount": 0.12,
    }


class TaobaoLiveCrawler(_GenericPlatformCrawler):
    platform_name = "淘宝直播"
    api_endpoints = {
        "sessions": "/router/rest",
        "realtime": "/router/rest",
        "orders": "/router/rest",
    }
    _cfg = {
        "id_prefix": "TB",
        "anchor_prefix": "淘宝主播",
        "title_prefix": "淘宝优选直播间",
        "sessions_range": (2, 6),
        "hour_range": (20, 23),
        "traffic_range": (80000, 800000),
        "subsidy_range": (8000, 80000),
        "gmv_range": (200000, 2000000),
        "target_range": (300000, 3000000),
        "viewer_range": (2000, 80000),
        "new_viewer_range": (200, 8000),
        "interaction_range": (100, 3000),
        "click_range": (50, 2000),
        "order_range": (10, 300),
        "gmv_rt_range": (1000, 100000),
        "order_count_range": (20, 150),
        "qty_range": (1, 8),
        "price_range": (39.9, 1999.9),
        "max_discount": 0.20,
    }


class WechatLiveCrawler(_GenericPlatformCrawler):
    platform_name = "视频号"
    api_endpoints = {
        "sessions": "/wxa/business/getliveinfo",
        "realtime": "/wxa/business/getliveroominfo",
        "orders": "/wxa/business/getliveorders",
    }
    _cfg = {
        "id_prefix": "WX",
        "anchor_prefix": "视频号主播",
        "title_prefix": "私域直播间",
        "sessions_range": (1, 3),
        "hour_range": (19, 22),
        "traffic_range": (10000, 100000),
        "subsidy_range": (1000, 10000),
        "gmv_range": (50000, 500000),
        "target_range": (100000, 1000000),
        "viewer_range": (200, 15000),
        "new_viewer_range": (20, 1500),
        "interaction_range": (20, 800),
        "click_range": (10, 500),
        "order_range": (2, 100),
        "gmv_rt_range": (200, 30000),
        "order_count_range": (5, 60),
        "qty_range": (1, 3),
        "price_range": (49.9, 1599.9),
        "max_discount": 0.10,
    }


class BiliBiliCrawler(_GenericPlatformCrawler):
    platform_name = "B站直播"
    api_endpoints = {
        "sessions": "/xlive/web-room/v1/index/getRoomBaseInfo",
        "realtime": "/xlive/web-room/v1/index/getInfoByRoom",
        "orders": "/xlive/app-room/v1/shop/shopMall/orders",
    }
    _cfg = {
        "id_prefix": "BZ",
        "anchor_prefix": "B站UP主播",
        "title_prefix": "B站带货",
        "sessions_range": (1, 2),
        "hour_range": (20, 23),
        "traffic_range": (5000, 80000),
        "subsidy_range": (500, 8000),
        "gmv_range": (30000, 300000),
        "target_range": (80000, 800000),
        "viewer_range": (100, 20000),
        "new_viewer_range": (10, 2000),
        "interaction_range": (30, 1000),
        "click_range": (5, 600),
        "order_range": (1, 80),
        "gmv_rt_range": (100, 25000),
        "order_count_range": (3, 50),
        "qty_range": (1, 4),
        "price_range": (59.9, 2499.9),
        "max_discount": 0.08,
    }


class CrawlerManager:
    def __init__(self):
        self.crawlers: Dict[str, BasePlatformCrawler] = {
            "抖音": DouyinCrawler(),
            "快手": KuaishouCrawler(),
            "淘宝直播": TaobaoLiveCrawler(),
            "视频号": WechatLiveCrawler(),
            "B站直播": BiliBiliCrawler(),
        }

    def get_crawler(self, platform: str) -> Optional[BasePlatformCrawler]:
        return self.crawlers.get(platform)

    def crawl_all_sessions(self, target_date: Optional[date] = None) -> List[Dict[str, Any]]:
        all_sessions = []
        for platform, crawler in self.crawlers.items():
            try:
                sessions = crawler.fetch_live_sessions(target_date)
                for s in sessions:
                    self._ensure_anchor(s["anchor_id"], s["anchor_name"], platform)
                all_sessions.extend(sessions)
                logger.info(f"[{platform}] 抓取到 {len(sessions)} 场直播")
            except Exception as e:
                logger.error(f"[{platform}] 抓取直播场次失败: {e}")
        self._save_sessions(all_sessions)
        return all_sessions

    def _ensure_anchor(self, anchor_id: str, name: str, platform: str):
        db = get_db_session()
        try:
            exists = db.query(Anchor).filter(Anchor.anchor_id == anchor_id).first()
            if not exists:
                anchor = Anchor(
                    anchor_id=anchor_id,
                    name=name,
                    platform=platform,
                    follower_count=random.randint(10000, 5000000),
                    commission_rate=round(random.uniform(0.15, 0.35), 2),
                )
                db.add(anchor)
                db.commit()
                logger.info(f"新增主播: {name} ({anchor_id}) on {platform}")
        except Exception as e:
            logger.error(f"确保主播存在失败: {e}")
            db.rollback()
        finally:
            db.close()

    def _save_sessions(self, sessions: List[Dict[str, Any]]):
        db = get_db_session()
        try:
            for s in sessions:
                existing = db.query(LiveSession).filter(LiveSession.session_id == s["session_id"]).first()
                if existing:
                    continue
                live = LiveSession(
                    session_id=s["session_id"],
                    anchor_id=s["anchor_id"],
                    platform=s["platform"],
                    title=s["title"],
                    start_time=s["start_time"],
                    estimated_traffic=s["estimated_traffic"],
                    estimated_subsidy=s["estimated_subsidy"],
                    estimated_gmv=s["estimated_gmv"],
                    target_gmv=s["target_gmv"],
                    status="live",
                )
                db.add(live)
                self._ensure_sample_products(db, s["session_id"])
            db.commit()
            logger.info(f"保存 {len(sessions)} 场直播数据")
        except Exception as e:
            logger.error(f"保存直播场次失败: {e}")
            db.rollback()
        finally:
            db.close()

    def _ensure_sample_products(self, db, session_id: str):
        for i in range(random.randint(5, 20)):
            sku = f"SKU{random.randint(1000, 9999)}"
            product = db.query(Product).filter(Product.sku == sku).first()
            if not product:
                cost = round(random.uniform(10, 500), 2)
                product = Product(
                    sku=sku,
                    name=f"商品_{sku}",
                    category=random.choice(["美妆", "服饰", "食品", "家电", "数码", "家居"]),
                    cost_price=cost,
                    sale_price=round(cost * random.uniform(1.5, 3.0), 2),
                    original_stock=random.randint(500, 5000),
                    current_stock=random.randint(50, 5000),
                    safety_stock=random.randint(50, 200),
                    supplier_id=f"SUP{random.randint(100, 999)}",
                    supplier_name=f"供应商{random.randint(1, 50)}",
                    logistics_days=random.randint(1, 7),
                )
                db.add(product)
            stock = random.randint(50, 500)
            lp = LiveProduct(
                session_id=session_id,
                product_sku=sku,
                sequence=i + 1,
                live_price=round(product.sale_price * random.uniform(0.7, 1.0), 2),
                live_stock=stock,
                on_shelf_time=datetime.now(),
            )
            db.add(lp)

    def collect_realtime_data(self, session_id: str, platform: str):
        crawler = self.get_crawler(platform)
        if not crawler:
            return None
        try:
            data = crawler.fetch_realtime_data(session_id)
            db = get_db_session()
            dp = RealtimeDataPoint(
                session_id=session_id,
                timestamp=datetime.now(),
                viewer_count=data["viewer_count"],
                new_viewers=data["new_viewers"],
                interaction_count=data["interaction_count"],
                click_count=data["click_count"],
                order_count=data["order_count"],
                gmv=data["gmv"],
            )
            db.add(dp)
            db.commit()
            db.close()
            return data
        except Exception as e:
            logger.error(f"收集实时数据失败 [{session_id}]: {e}")
            return None

    def collect_orders(self, session_id: str, platform: str):
        crawler = self.get_crawler(platform)
        if not crawler:
            return []
        try:
            orders = crawler.fetch_orders(session_id)
            db = get_db_session()
            for o in orders:
                exists = db.query(Order).filter(Order.order_id == o["order_id"]).first()
                if exists:
                    continue
                paid = round(o["total_amount"] - o["discount_amount"], 2)
                session = db.query(LiveSession).filter(LiveSession.session_id == session_id).first()
                order = Order(
                    order_id=o["order_id"],
                    session_id=session_id,
                    product_sku=o["product_sku"],
                    anchor_id=session.anchor_id if session else None,
                    platform=session.platform if session else platform,
                    quantity=o["quantity"],
                    unit_price=o["unit_price"],
                    total_amount=o["total_amount"],
                    discount_amount=o["discount_amount"],
                    paid_amount=paid,
                    status=random.choice(["pending", "paid", "shipped", "completed"]),
                    order_time=datetime.now(),
                )
                db.add(order)
            db.commit()
            db.close()
            logger.info(f"[{session_id}] 新增 {len(orders)} 条订单")
            return orders
        except Exception as e:
            logger.error(f"采集订单失败 [{session_id}]: {e}")
            return []


crawler_manager = CrawlerManager()

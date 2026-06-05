import uuid
import random
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from tenacity import retry, stop_after_attempt, wait_exponential
from app import logger, get_db_session
from app.models import (
    LiveSession, RealtimeDataPoint, LiveProduct, Order, Anchor, Product
)
from config import settings


class BasePlatformCrawler:
    platform_name: str = "base"

    def __init__(self):
        self.session = None

    def _to_datetime(self, d) -> datetime:
        if isinstance(d, datetime):
            return d
        if isinstance(d, date):
            return datetime.combine(d, datetime.min.time())
        return datetime.now()

    def generate_session_id(self) -> str:
        return f"{self.platform_name.upper()}_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def fetch_live_sessions(self, target_date: Optional[date] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def fetch_realtime_data(self, session_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def fetch_orders(self, session_id: str, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError


class DouyinCrawler(BasePlatformCrawler):
    platform_name = "抖音"

    def fetch_live_sessions(self, target_date=None):
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

    def fetch_realtime_data(self, session_id: str):
        return {
            "viewer_count": random.randint(1000, 50000),
            "new_viewers": random.randint(100, 5000),
            "interaction_count": random.randint(50, 2000),
            "click_count": random.randint(20, 1000),
            "order_count": random.randint(5, 200),
            "gmv": random.uniform(500, 50000),
        }

    def fetch_orders(self, session_id: str, since=None):
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


class KuaishouCrawler(BasePlatformCrawler):
    platform_name = "快手"

    def fetch_live_sessions(self, target_date=None):
        sessions = []
        for i in range(random.randint(1, 4)):
            start_time = self._to_datetime(target_date)
            start_time = start_time.replace(hour=random.randint(19, 23), minute=random.randint(0, 59))
            sessions.append({
                "session_id": self.generate_session_id(),
                "anchor_id": f"KS_{random.randint(1000, 9999)}",
                "anchor_name": f"快手主播{i+1}",
                "platform": self.platform_name,
                "title": f"老铁直播间{i+1}",
                "start_time": start_time,
                "estimated_traffic": random.randint(30000, 300000),
                "estimated_subsidy": random.uniform(3000, 30000),
                "estimated_gmv": random.uniform(80000, 800000),
                "target_gmv": random.uniform(150000, 1500000),
            })
        return sessions

    def fetch_realtime_data(self, session_id: str):
        return {
            "viewer_count": random.randint(800, 40000),
            "new_viewers": random.randint(80, 4000),
            "interaction_count": random.randint(40, 1500),
            "click_count": random.randint(15, 800),
            "order_count": random.randint(3, 150),
            "gmv": random.uniform(400, 40000),
        }

    def fetch_orders(self, session_id: str, since=None):
        orders = []
        for _ in range(random.randint(8, 80)):
            sku = f"SKU{random.randint(1000, 9999)}"
            qty = random.randint(1, 5)
            price = random.uniform(19.9, 899.9)
            orders.append({
                "order_id": f"ORD_{uuid.uuid4().hex[:12]}",
                "session_id": session_id,
                "product_sku": sku,
                "quantity": qty,
                "unit_price": price,
                "total_amount": round(qty * price, 2),
                "discount_amount": round(qty * price * random.uniform(0, 0.12), 2),
            })
        return orders


class TaobaoLiveCrawler(BasePlatformCrawler):
    platform_name = "淘宝直播"

    def fetch_live_sessions(self, target_date=None):
        sessions = []
        for i in range(random.randint(2, 6)):
            start_time = self._to_datetime(target_date)
            start_time = start_time.replace(hour=random.randint(20, 23), minute=random.randint(0, 59))
            sessions.append({
                "session_id": self.generate_session_id(),
                "anchor_id": f"TB_{random.randint(1000, 9999)}",
                "anchor_name": f"淘宝主播{i+1}",
                "platform": self.platform_name,
                "title": f"淘宝优选直播间{i+1}",
                "start_time": start_time,
                "estimated_traffic": random.randint(80000, 800000),
                "estimated_subsidy": random.uniform(8000, 80000),
                "estimated_gmv": random.uniform(200000, 2000000),
                "target_gmv": random.uniform(300000, 3000000),
            })
        return sessions

    def fetch_realtime_data(self, session_id: str):
        return {
            "viewer_count": random.randint(2000, 80000),
            "new_viewers": random.randint(200, 8000),
            "interaction_count": random.randint(100, 3000),
            "click_count": random.randint(50, 2000),
            "order_count": random.randint(10, 300),
            "gmv": random.uniform(1000, 100000),
        }

    def fetch_orders(self, session_id: str, since=None):
        orders = []
        for _ in range(random.randint(20, 150)):
            sku = f"SKU{random.randint(1000, 9999)}"
            qty = random.randint(1, 8)
            price = random.uniform(39.9, 1999.9)
            orders.append({
                "order_id": f"ORD_{uuid.uuid4().hex[:12]}",
                "session_id": session_id,
                "product_sku": sku,
                "quantity": qty,
                "unit_price": price,
                "total_amount": round(qty * price, 2),
                "discount_amount": round(qty * price * random.uniform(0, 0.20), 2),
            })
        return orders


class WechatLiveCrawler(BasePlatformCrawler):
    platform_name = "视频号"

    def fetch_live_sessions(self, target_date=None):
        sessions = []
        for i in range(random.randint(1, 3)):
            start_time = self._to_datetime(target_date)
            start_time = start_time.replace(hour=random.randint(19, 22), minute=random.randint(0, 59))
            sessions.append({
                "session_id": self.generate_session_id(),
                "anchor_id": f"WX_{random.randint(1000, 9999)}",
                "anchor_name": f"视频号主播{i+1}",
                "platform": self.platform_name,
                "title": f"私域直播间{i+1}",
                "start_time": start_time,
                "estimated_traffic": random.randint(10000, 100000),
                "estimated_subsidy": random.uniform(1000, 10000),
                "estimated_gmv": random.uniform(50000, 500000),
                "target_gmv": random.uniform(100000, 1000000),
            })
        return sessions

    def fetch_realtime_data(self, session_id: str):
        return {
            "viewer_count": random.randint(200, 15000),
            "new_viewers": random.randint(20, 1500),
            "interaction_count": random.randint(20, 800),
            "click_count": random.randint(10, 500),
            "order_count": random.randint(2, 100),
            "gmv": random.uniform(200, 30000),
        }

    def fetch_orders(self, session_id: str, since=None):
        orders = []
        for _ in range(random.randint(5, 60)):
            sku = f"SKU{random.randint(1000, 9999)}"
            qty = random.randint(1, 3)
            price = random.uniform(49.9, 1599.9)
            orders.append({
                "order_id": f"ORD_{uuid.uuid4().hex[:12]}",
                "session_id": session_id,
                "product_sku": sku,
                "quantity": qty,
                "unit_price": price,
                "total_amount": round(qty * price, 2),
                "discount_amount": round(qty * price * random.uniform(0, 0.10), 2),
            })
        return orders


class BiliBiliCrawler(BasePlatformCrawler):
    platform_name = "B站直播"

    def fetch_live_sessions(self, target_date=None):
        sessions = []
        for i in range(random.randint(1, 2)):
            start_time = self._to_datetime(target_date)
            start_time = start_time.replace(hour=random.randint(20, 23), minute=random.randint(0, 59))
            sessions.append({
                "session_id": self.generate_session_id(),
                "anchor_id": f"BZ_{random.randint(1000, 9999)}",
                "anchor_name": f"B站UP主播{i+1}",
                "platform": self.platform_name,
                "title": f"B站带货{i+1}期",
                "start_time": start_time,
                "estimated_traffic": random.randint(5000, 80000),
                "estimated_subsidy": random.uniform(500, 8000),
                "estimated_gmv": random.uniform(30000, 300000),
                "target_gmv": random.uniform(80000, 800000),
            })
        return sessions

    def fetch_realtime_data(self, session_id: str):
        return {
            "viewer_count": random.randint(100, 20000),
            "new_viewers": random.randint(10, 2000),
            "interaction_count": random.randint(30, 1000),
            "click_count": random.randint(5, 600),
            "order_count": random.randint(1, 80),
            "gmv": random.uniform(100, 25000),
        }

    def fetch_orders(self, session_id: str, since=None):
        orders = []
        for _ in range(random.randint(3, 50)):
            sku = f"SKU{random.randint(1000, 9999)}"
            qty = random.randint(1, 4)
            price = random.uniform(59.9, 2499.9)
            orders.append({
                "order_id": f"ORD_{uuid.uuid4().hex[:12]}",
                "session_id": session_id,
                "product_sku": sku,
                "quantity": qty,
                "unit_price": price,
                "total_amount": round(qty * price, 2),
                "discount_amount": round(qty * price * random.uniform(0, 0.08), 2),
            })
        return orders


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

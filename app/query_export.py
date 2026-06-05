import uuid
import csv
import io
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
from sqlalchemy import and_, or_, func

from app import logger, get_db_session
from app.models import (
    LiveSession, Order, LiveProduct, Product, Anchor,
    RealtimeDataPoint, AnchorPerformance
)
from config import EXPORT_DIR

try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except Exception:
    OPENPYXL_AVAILABLE = False
    logger.warning("openpyxl 不可用，Excel导出将自动降级为CSV")

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except Exception:
    PANDAS_AVAILABLE = False
    logger.warning("pandas 不可用，将使用纯Python CSV导出")


class QueryService:
    def query_live_sessions(
        self,
        anchor_id: Optional[str] = None,
        product_sku: Optional[str] = None,
        platform: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        min_gmv: Optional[float] = None,
        max_gmv: Optional[float] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict:
        db = get_db_session()
        try:
            query = db.query(LiveSession)

            if anchor_id:
                query = query.filter(LiveSession.anchor_id == anchor_id)
            if platform:
                query = query.filter(LiveSession.platform == platform)
            if status:
                query = query.filter(LiveSession.status == status)
            if start_date:
                query = query.filter(LiveSession.start_time >= datetime.combine(start_date, datetime.min.time()))
            if end_date:
                query = query.filter(LiveSession.start_time <= datetime.combine(end_date, datetime.max.time()))
            if min_gmv is not None:
                query = query.filter(LiveSession.total_gmv >= min_gmv)
            if max_gmv is not None:
                query = query.filter(LiveSession.total_gmv <= max_gmv)
            if product_sku:
                query = query.join(LiveProduct, LiveSession.session_id == LiveProduct.session_id)
                query = query.filter(LiveProduct.product_sku == product_sku)

            total = query.count()
            sessions = (
                query.order_by(LiveSession.start_time.desc())
                .distinct()
                .offset(offset)
                .limit(limit)
                .all()
            )

            items = []
            for s in sessions:
                anchor = db.query(Anchor).filter(Anchor.anchor_id == s.anchor_id).first()
                items.append({
                    "session_id": s.session_id,
                    "anchor_id": s.anchor_id,
                    "anchor_name": anchor.name if anchor else "",
                    "platform": s.platform,
                    "title": s.title,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "status": s.status,
                    "total_viewers": s.total_viewers,
                    "peak_viewers": s.peak_viewers,
                    "total_gmv": s.total_gmv,
                    "total_profit": s.total_profit,
                    "roi": s.roi,
                    "paid_orders": s.paid_orders,
                    "click_conversion_rate": s.click_conversion_rate,
                    "return_rate": s.return_rate,
                    "gmv_achievement_rate": s.gmv_achievement_rate,
                })

            return {
                "total": total,
                "items": items,
                "limit": limit,
                "offset": offset,
            }
        finally:
            db.close()

    def query_orders(
        self,
        session_id: Optional[str] = None,
        anchor_id: Optional[str] = None,
        product_sku: Optional[str] = None,
        platform: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        status: Optional[str] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> Dict:
        db = get_db_session()
        try:
            query = db.query(Order)

            if session_id:
                query = query.filter(Order.session_id == session_id)
            if anchor_id:
                query = query.filter(Order.anchor_id == anchor_id)
            if product_sku:
                query = query.filter(Order.product_sku == product_sku)
            if platform:
                query = query.filter(Order.platform == platform)
            if status:
                query = query.filter(Order.status == status)
            if start_date:
                query = query.filter(Order.order_time >= datetime.combine(start_date, datetime.min.time()))
            if end_date:
                query = query.filter(Order.order_time <= datetime.combine(end_date, datetime.max.time()))
            if min_amount is not None:
                query = query.filter(Order.paid_amount >= min_amount)
            if max_amount is not None:
                query = query.filter(Order.paid_amount <= max_amount)

            total = query.count()
            orders = query.order_by(Order.order_time.desc()).offset(offset).limit(limit).all()

            items = [
                {
                    "order_id": o.order_id,
                    "session_id": o.session_id,
                    "anchor_id": o.anchor_id,
                    "product_sku": o.product_sku,
                    "platform": o.platform,
                    "user_id": o.user_id,
                    "quantity": o.quantity,
                    "unit_price": o.unit_price,
                    "total_amount": o.total_amount,
                    "discount_amount": o.discount_amount,
                    "paid_amount": o.paid_amount,
                    "profit": o.profit,
                    "status": o.status,
                    "order_time": o.order_time,
                    "paid_time": o.paid_time,
                    "promotion_id": o.promotion_id,
                }
                for o in orders
            ]

            return {
                "total": total,
                "items": items,
                "limit": limit,
                "offset": offset,
            }
        finally:
            db.close()

    def query_products(
        self,
        sku: Optional[str] = None,
        name: Optional[str] = None,
        category: Optional[str] = None,
        supplier_id: Optional[str] = None,
        status: Optional[str] = None,
        min_stock: Optional[int] = None,
        max_stock: Optional[int] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict:
        db = get_db_session()
        try:
            query = db.query(Product)

            if sku:
                query = query.filter(Product.sku == sku)
            if name:
                query = query.filter(Product.name.like(f"%{name}%"))
            if category:
                query = query.filter(Product.category == category)
            if supplier_id:
                query = query.filter(Product.supplier_id == supplier_id)
            if status:
                query = query.filter(Product.status == status)
            if min_stock is not None:
                query = query.filter(Product.current_stock >= min_stock)
            if max_stock is not None:
                query = query.filter(Product.current_stock <= max_stock)

            total = query.count()
            products = query.order_by(Product.updated_at.desc()).offset(offset).limit(limit).all()

            items = [
                {
                    "sku": p.sku,
                    "name": p.name,
                    "category": p.category,
                    "brand": p.brand,
                    "cost_price": p.cost_price,
                    "sale_price": p.sale_price,
                    "original_stock": p.original_stock,
                    "current_stock": p.current_stock,
                    "safety_stock": p.safety_stock,
                    "supplier_id": p.supplier_id,
                    "supplier_name": p.supplier_name,
                    "logistics_days": p.logistics_days,
                    "status": p.status,
                    "created_at": p.created_at,
                }
                for p in products
            ]

            return {"total": total, "items": items, "limit": limit, "offset": offset}
        finally:
            db.close()

    def query_anchors(
        self,
        anchor_id: Optional[str] = None,
        name: Optional[str] = None,
        platform: Optional[str] = None,
        level: Optional[str] = None,
        status: Optional[str] = None,
        min_score: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict:
        db = get_db_session()
        try:
            query = db.query(Anchor)

            if anchor_id:
                query = query.filter(Anchor.anchor_id == anchor_id)
            if name:
                query = query.filter(Anchor.name.like(f"%{name}%"))
            if platform:
                query = query.filter(Anchor.platform == platform)
            if level:
                query = query.filter(Anchor.level == level)
            if status:
                query = query.filter(Anchor.status == status)
            if min_score is not None:
                query = query.filter(Anchor.performance_score >= min_score)

            total = query.count()
            anchors = query.order_by(Anchor.performance_score.desc()).offset(offset).limit(limit).all()

            items = [
                {
                    "anchor_id": a.anchor_id,
                    "name": a.name,
                    "platform": a.platform,
                    "follower_count": a.follower_count,
                    "level": a.level,
                    "commission_rate": a.commission_rate,
                    "performance_score": a.performance_score,
                    "performance_level": a.performance_level,
                    "status": a.status,
                    "join_date": a.join_date,
                }
                for a in anchors
            ]

            return {"total": total, "items": items, "limit": limit, "offset": offset}
        finally:
            db.close()


class BatchExporter:
    def __init__(self):
        self.query_service = QueryService()

    def export_live_sessions(
        self,
        format: str = "xlsx",
        **filters,
    ) -> str:
        filters["limit"] = 100000
        result = self.query_service.query_live_sessions(**filters)
        return self._export(result["items"], f"live_sessions_{datetime.now().strftime('%Y%m%d%H%M%S')}", format, [
            "session_id", "anchor_id", "anchor_name", "platform", "title",
            "start_time", "end_time", "status", "total_viewers", "peak_viewers",
            "total_gmv", "total_profit", "roi", "paid_orders",
            "click_conversion_rate", "return_rate", "gmv_achievement_rate",
        ])

    def export_orders(
        self,
        format: str = "xlsx",
        **filters,
    ) -> str:
        filters["limit"] = 500000
        result = self.query_service.query_orders(**filters)
        return self._export(result["items"], f"orders_{datetime.now().strftime('%Y%m%d%H%M%S')}", format, [
            "order_id", "session_id", "anchor_id", "product_sku", "platform",
            "quantity", "unit_price", "total_amount", "discount_amount",
            "paid_amount", "profit", "status", "order_time", "paid_time",
        ])

    def export_products(
        self,
        format: str = "xlsx",
        **filters,
    ) -> str:
        filters["limit"] = 50000
        result = self.query_service.query_products(**filters)
        return self._export(result["items"], f"products_{datetime.now().strftime('%Y%m%d%H%M%S')}", format, [
            "sku", "name", "category", "brand", "cost_price", "sale_price",
            "original_stock", "current_stock", "safety_stock",
            "supplier_id", "supplier_name", "logistics_days", "status",
        ])

    def _to_cell(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, float):
            return f"{value:.6f}".rstrip("0").rstrip(".")
        return str(value)

    def _export(self, items: List[Dict], filename: str, format: str, columns: List[str]) -> str:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        use_format = format.lower()

        if use_format == "xlsx" and not OPENPYXL_AVAILABLE:
            logger.warning("openpyxl不可用，自动降级为CSV导出")
            use_format = "csv"

        if not items:
            items = []
        existing_cols = columns if columns else list(items[0].keys()) if items else []

        if use_format == "csv":
            path = EXPORT_DIR / f"{filename}.csv"
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(existing_cols)
                for item in items:
                    writer.writerow([self._to_cell(item.get(c)) for c in existing_cols])
            logger.info(f"导出 CSV: {path} ({len(items)}条)")
            return str(path)

        else:
            if PANDAS_AVAILABLE and OPENPYXL_AVAILABLE:
                try:
                    path = EXPORT_DIR / f"{filename}.xlsx"
                    df = pd.DataFrame(items)
                    if existing_cols:
                        valid_cols = [c for c in existing_cols if c in df.columns]
                        df = df[valid_cols]
                    df.to_excel(path, index=False, engine="openpyxl")
                    logger.info(f"导出 Excel: {path} ({len(items)}条)")
                    return str(path)
                except Exception as e:
                    logger.warning(f"pandas Excel导出失败，降级为CSV: {e}")
            path = EXPORT_DIR / f"{filename}.csv"
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(existing_cols)
                for item in items:
                    writer.writerow([self._to_cell(item.get(c)) for c in existing_cols])
            logger.info(f"导出 CSV: {path} ({len(items)}条)")
            return str(path)


query_service = QueryService()
batch_exporter = BatchExporter()

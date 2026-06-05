from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy import func, and_, or_
import pandas as pd
import numpy as np
from app import logger, get_db_session
from app.models import (
    LiveSession, LiveProduct, Order, Product, RealtimeDataPoint, Anchor
)
from config import settings


class MetricsCalculator:
    @staticmethod
    def calc_roi(profit: float, cost: float) -> float:
        if cost <= 0:
            return 0.0
        return round(profit / cost, 4)

    @staticmethod
    def calc_gmv_achievement_rate(actual_gmv: float, target_gmv: float) -> float:
        if target_gmv <= 0:
            return 0.0
        return round(actual_gmv / target_gmv, 4)

    @staticmethod
    def calc_sell_out_rate(sold_qty: int, original_stock: int) -> float:
        if original_stock <= 0:
            return 0.0
        return round(sold_qty / original_stock, 4)

    @staticmethod
    def calc_conversion_rate(orders: int, clicks: int) -> float:
        if clicks <= 0:
            return 0.0
        return round(orders / clicks, 4)

    @staticmethod
    def calc_return_rate(return_count: int, total_orders: int) -> float:
        if total_orders <= 0:
            return 0.0
        return round(return_count / total_orders, 4)

    @staticmethod
    def calc_interaction_rate(interactions: int, viewers: int) -> float:
        if viewers <= 0:
            return 0.0
        return round(interactions / viewers, 4)

    @staticmethod
    def calc_profit(amount: float, cost: float, traffic_cost: float = 0, commission: float = 0) -> float:
        return round(amount - cost - traffic_cost - commission, 2)


class LiveSessionAnalyzer:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.db = get_db_session()
        self.session = self.db.query(LiveSession).filter(LiveSession.session_id == session_id).first()

    def close(self):
        self.db.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def compute_session_metrics(self) -> Dict:
        if not self.session:
            return {}

        paid_orders = (
            self.db.query(func.coalesce(func.sum(Order.quantity), 0))
            .filter(and_(Order.session_id == self.session_id, Order.status.in_(["paid", "shipped", "completed"])))
            .scalar() or 0
        )

        total_gmv = (
            self.db.query(func.coalesce(func.sum(Order.paid_amount), 0.0))
            .filter(and_(Order.session_id == self.session_id, Order.status.in_(["paid", "shipped", "completed"])))
            .scalar() or 0.0
        )

        total_cost = (
            self.db.query(func.coalesce(func.sum(Order.cost_amount), 0.0))
            .filter(and_(Order.session_id == self.session_id, Order.status.in_(["paid", "shipped", "completed"])))
            .scalar() or 0.0
        )

        total_return_amount = (
            self.db.query(func.coalesce(func.sum(Order.paid_amount), 0.0))
            .filter(and_(Order.session_id == self.session_id, Order.status == "returned"))
            .scalar() or 0.0
        )

        total_orders_count = (
            self.db.query(func.count(Order.id))
            .filter(Order.session_id == self.session_id)
            .scalar() or 0
        )

        return_count = (
            self.db.query(func.count(Order.id))
            .filter(and_(Order.session_id == self.session_id, Order.status == "returned"))
            .scalar() or 0
        )

        data_points = (
            self.db.query(RealtimeDataPoint)
            .filter(RealtimeDataPoint.session_id == self.session_id)
            .order_by(RealtimeDataPoint.timestamp)
            .all()
        )

        total_viewers = 0
        peak_viewers = 0
        total_interactions = 0
        total_clicks = 0

        for dp in data_points:
            total_viewers += dp.new_viewers
            peak_viewers = max(peak_viewers, dp.viewer_count)
            total_interactions += dp.interaction_count
            total_clicks += dp.click_count

        avg_viewers = int(np.mean([dp.viewer_count for dp in data_points])) if data_points else 0
        traffic_cost = self.session.traffic_cost or (total_viewers * random.uniform(0.05, 0.3))

        anchor = self.db.query(Anchor).filter(Anchor.anchor_id == self.session.anchor_id).first()
        commission_rate = anchor.commission_rate if anchor else 0.2
        commission = total_gmv * commission_rate

        profit = MetricsCalculator.calc_profit(total_gmv, total_cost, traffic_cost, commission)
        roi = MetricsCalculator.calc_roi(profit, total_cost + traffic_cost + commission)
        gmv_achievement = MetricsCalculator.calc_gmv_achievement_rate(total_gmv, self.session.target_gmv)
        interaction_rate = MetricsCalculator.calc_interaction_rate(total_interactions, total_viewers)
        conversion_rate = MetricsCalculator.calc_conversion_rate(paid_orders, total_clicks)
        return_rate = MetricsCalculator.calc_return_rate(return_count, total_orders_count)

        self.session.actual_traffic = total_viewers
        self.session.peak_viewers = peak_viewers
        self.session.avg_viewers = avg_viewers
        self.session.total_viewers = total_viewers
        self.session.interaction_count = total_interactions
        self.session.interaction_rate = interaction_rate
        self.session.click_count = total_clicks
        self.session.click_conversion_rate = conversion_rate
        self.session.total_orders = total_orders_count
        self.session.paid_orders = paid_orders
        self.session.total_gmv = round(total_gmv, 2)
        self.session.total_profit = profit
        self.session.return_count = return_count
        self.session.return_amount = round(total_return_amount, 2)
        self.session.return_rate = return_rate
        self.session.traffic_cost = round(traffic_cost, 2)
        self.session.roi = roi
        self.session.gmv_achievement_rate = gmv_achievement
        self.session.updated_at = datetime.now()

        self.db.commit()

        return {
            "session_id": self.session_id,
            "total_gmv": total_gmv,
            "total_profit": profit,
            "roi": roi,
            "gmv_achievement_rate": gmv_achievement,
            "interaction_rate": interaction_rate,
            "conversion_rate": conversion_rate,
            "return_rate": return_rate,
            "total_viewers": total_viewers,
            "peak_viewers": peak_viewers,
            "paid_orders": paid_orders,
        }

    def compute_product_metrics(self) -> List[Dict]:
        if not self.session:
            return []

        live_products = self.db.query(LiveProduct).filter(LiveProduct.session_id == self.session_id).all()
        results = []

        for lp in live_products:
            product = self.db.query(Product).filter(Product.sku == lp.product_sku).first()
            if not product:
                continue

            orders_query = self.db.query(Order).filter(
                and_(Order.session_id == self.session_id, Order.product_sku == lp.product_sku)
            )
            orders = orders_query.all()

            paid_qty = sum(o.quantity for o in orders if o.status in ["paid", "shipped", "completed"])
            paid_amount = sum(o.paid_amount for o in orders if o.status in ["paid", "shipped", "completed"])
            cost_amount = sum(o.cost_amount for o in orders if o.status in ["paid", "shipped", "completed"])
            return_count = sum(1 for o in orders if o.status == "returned")

            clicks = lp.click_count or max(paid_qty * random.randint(3, 10), 0)
            profit = paid_amount - cost_amount
            sell_out_rate = MetricsCalculator.calc_sell_out_rate(paid_qty, product.original_stock)
            conversion_rate = MetricsCalculator.calc_conversion_rate(paid_qty, clicks)
            return_rate = MetricsCalculator.calc_return_rate(return_count, len(orders)) if orders else 0.0

            lp.sold_quantity = paid_qty
            lp.sold_amount = round(paid_amount, 2)
            lp.click_count = clicks
            lp.conversion_rate = conversion_rate
            lp.return_count = return_count
            lp.return_rate = return_rate
            lp.profit = round(profit, 2)
            lp.sell_out_rate = sell_out_rate
            lp.updated_at = datetime.now()

            product.current_stock = max(product.original_stock - paid_qty, 0)
            product.updated_at = datetime.now()

            results.append({
                "product_sku": lp.product_sku,
                "sold_quantity": paid_qty,
                "sold_amount": paid_amount,
                "profit": profit,
                "sell_out_rate": sell_out_rate,
                "conversion_rate": conversion_rate,
                "return_rate": return_rate,
                "current_stock": product.current_stock,
            })

        self.db.commit()
        return results


class AnalyticsEngine:
    @staticmethod
    def compare_vs_estimate(session_id: str) -> Dict:
        db = get_db_session()
        try:
            session = db.query(LiveSession).filter(LiveSession.session_id == session_id).first()
            if not session:
                return {}
            traffic_ratio = (session.actual_traffic / session.estimated_traffic) if session.estimated_traffic else 0
            subsidy_diff = session.actual_subsidy - session.estimated_subsidy
            gmv_ratio = (session.total_gmv / session.estimated_gmv) if session.estimated_gmv else 0
            return {
                "session_id": session_id,
                "traffic_ratio": round(traffic_ratio, 4),
                "traffic_status": "达标" if traffic_ratio >= 0.8 else "未达标",
                "subsidy_diff": round(subsidy_diff, 2),
                "subsidy_status": "超支" if subsidy_diff > 0 else "节余",
                "gmv_ratio": round(gmv_ratio, 4),
                "gmv_status": "达标" if gmv_ratio >= 1.0 else "未达标",
            }
        finally:
            db.close()

    @staticmethod
    def get_product_return_trend(sku: str, days: int = 7) -> pd.DataFrame:
        db = get_db_session()
        try:
            start = date.today() - timedelta(days=days - 1)
            orders = (
                db.query(Order)
                .filter(
                    and_(
                        Order.product_sku == sku,
                        Order.order_time >= datetime.combine(start, datetime.min.time()),
                    )
                )
                .all()
            )
            records = []
            for o in orders:
                records.append({
                    "date": o.order_time.date(),
                    "is_returned": 1 if o.status == "returned" else 0,
                    "count": 1,
                })
            if not records:
                return pd.DataFrame(columns=["date", "return_rate", "order_count"])
            df = pd.DataFrame(records)
            grouped = df.groupby("date").agg(
                order_count=("count", "sum"),
                return_count=("is_returned", "sum"),
            ).reset_index()
            grouped["return_rate"] = grouped.apply(
                lambda r: round(r["return_count"] / r["order_count"], 4) if r["order_count"] else 0, axis=1
            )
            return grouped
        finally:
            db.close()

    @staticmethod
    def get_platform_summary(target_date: Optional[date] = None) -> pd.DataFrame:
        db = get_db_session()
        try:
            if not target_date:
                target_date = date.today()
            start = datetime.combine(target_date, datetime.min.time())
            end = datetime.combine(target_date, datetime.max.time())

            sessions = db.query(LiveSession).filter(
                and_(LiveSession.start_time >= start, LiveSession.start_time <= end)
            ).all()

            data = []
            for s in sessions:
                data.append({
                    "platform": s.platform,
                    "gmv": s.total_gmv or 0,
                    "profit": s.total_profit or 0,
                    "traffic_cost": s.traffic_cost or 0,
                    "orders": s.paid_orders or 0,
                    "viewers": s.total_viewers or 0,
                    "sessions": 1,
                })
            if not data:
                return pd.DataFrame()
            df = pd.DataFrame(data)
            summary = df.groupby("platform").agg({
                "gmv": "sum",
                "profit": "sum",
                "traffic_cost": "sum",
                "orders": "sum",
                "viewers": "sum",
                "sessions": "count",
            }).reset_index()
            summary["roi"] = summary.apply(
                lambda r: round(r["profit"] / (r["traffic_cost"] + 0.0001), 4), axis=1
            )
            return summary
        finally:
            db.close()

    @staticmethod
    def get_anchor_ranking(target_date: Optional[date] = None, top_n: int = 20) -> pd.DataFrame:
        db = get_db_session()
        try:
            if not target_date:
                target_date = date.today()
            start = datetime.combine(target_date - timedelta(days=6), datetime.min.time())
            end = datetime.combine(target_date, datetime.max.time())

            sessions = db.query(LiveSession).filter(
                and_(LiveSession.start_time >= start, LiveSession.start_time <= end)
            ).all()

            data = []
            for s in sessions:
                anchor = db.query(Anchor).filter(Anchor.anchor_id == s.anchor_id).first()
                data.append({
                    "anchor_id": s.anchor_id,
                    "anchor_name": anchor.name if anchor else s.anchor_id,
                    "platform": s.platform,
                    "gmv": s.total_gmv or 0,
                    "profit": s.total_profit or 0,
                    "interaction_rate": s.interaction_rate or 0,
                    "conversion_rate": s.click_conversion_rate or 0,
                })
            if not data:
                return pd.DataFrame()
            df = pd.DataFrame(data)
            grouped = df.groupby(["anchor_id", "anchor_name", "platform"]).agg({
                "gmv": "sum",
                "profit": "sum",
                "interaction_rate": "mean",
                "conversion_rate": "mean",
            }).reset_index()
            grouped = grouped.sort_values("gmv", ascending=False).head(top_n)
            return grouped
        finally:
            db.close()

    @staticmethod
    def get_gmv_trend(days: int = 30) -> pd.DataFrame:
        db = get_db_session()
        try:
            start = date.today() - timedelta(days=days - 1)
            sessions = db.query(LiveSession).filter(
                LiveSession.start_time >= datetime.combine(start, datetime.min.time())
            ).all()
            data = [{"date": s.start_time.date(), "gmv": s.total_gmv or 0} for s in sessions]
            if not data:
                return pd.DataFrame(columns=["date", "gmv"])
            df = pd.DataFrame(data)
            grouped = df.groupby("date")["gmv"].sum().reset_index()
            grouped = grouped.sort_values("date")
            full_dates = pd.date_range(start=start, end=date.today(), freq="D")
            grouped["date"] = pd.to_datetime(grouped["date"])
            grouped = grouped.set_index("date").reindex(full_dates, fill_value=0).reset_index()
            grouped.columns = ["date", "gmv"]
            grouped["date"] = grouped["date"].dt.date
            return grouped
        finally:
            db.close()


import random

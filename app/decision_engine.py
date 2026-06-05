import uuid
import random
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy import func, and_
import pandas as pd
import numpy as np
from app import logger, get_db_session
from app.models import (
    LiveProduct, Product, LiveSession, Order, RestockAlert,
    QualityAlert, AnchorPerformance, Anchor, Supplier
)
from app.analytics_engine import AnalyticsEngine, MetricsCalculator
from config import settings


class RestockManager:
    def __init__(self):
        self.threshold = settings.SELL_OUT_THRESHOLD

    def check_and_generate_alerts(self, session_id: Optional[str] = None) -> List[Dict]:
        db = get_db_session()
        alerts = []
        try:
            query = db.query(LiveProduct).join(Product, LiveProduct.product_sku == Product.sku)
            if session_id:
                query = query.filter(LiveProduct.session_id == session_id)

            live_products = query.all()

            for lp in live_products:
                product = db.query(Product).filter(Product.sku == lp.product_sku).first()
                if not product:
                    continue

                sell_out_rate = lp.sell_out_rate or MetricsCalculator.calc_sell_out_rate(
                    lp.sold_quantity or 0, product.original_stock or 1
                )

                if sell_out_rate >= self.threshold and product.current_stock <= product.safety_stock:
                    existing = (
                        db.query(RestockAlert)
                        .filter(
                            and_(
                                RestockAlert.product_sku == lp.product_sku,
                                RestockAlert.status == "pending",
                                RestockAlert.created_at >= datetime.now() - timedelta(hours=6),
                            )
                        )
                        .first()
                    )
                    if existing:
                        continue

                    suggested_qty = self._calc_suggested_quantity(product, lp)
                    plan = self._generate_restock_plan(product, suggested_qty)

                    alert = RestockAlert(
                        alert_id=f"RA_{uuid.uuid4().hex[:12]}",
                        product_sku=lp.product_sku,
                        product_name=product.name,
                        session_id=lp.session_id,
                        current_stock=product.current_stock,
                        original_stock=product.original_stock,
                        sell_out_rate=round(sell_out_rate, 4),
                        suggested_quantity=suggested_qty,
                        supplier_id=plan["supplier_id"],
                        supplier_name=plan["supplier_name"],
                        estimated_delivery_days=plan["delivery_days"],
                        estimated_cost=round(plan["estimated_cost"], 2),
                        priority="urgent" if sell_out_rate >= 0.95 else ("high" if sell_out_rate >= 0.9 else "normal"),
                        status="pending",
                        pushed_to_purchase=False,
                        purchase_notes=plan["notes"],
                    )
                    db.add(alert)
                    db.flush()

                    alerts.append({
                        "alert_id": alert.alert_id,
                        "product_sku": lp.product_sku,
                        "product_name": product.name,
                        "sell_out_rate": sell_out_rate,
                        "suggested_quantity": suggested_qty,
                        "supplier": plan["supplier_name"],
                        "estimated_delivery_days": plan["delivery_days"],
                        "estimated_cost": plan["estimated_cost"],
                        "priority": alert.priority,
                    })

            db.commit()
            if alerts:
                logger.info(f"生成 {len(alerts)} 条补货预警")
            return alerts
        except Exception as e:
            logger.error(f"生成补货预警失败: {e}")
            db.rollback()
            return []
        finally:
            db.close()

    def _calc_suggested_quantity(self, product: Product, lp: LiveProduct) -> int:
        avg_sales_per_hour = (lp.sold_quantity or 0) / max(self._session_duration_hours(lp.session_id), 1)
        safety_buffer_days = 3
        return int(avg_sales_per_hour * 8 * safety_buffer_days + product.safety_stock)

    def _session_duration_hours(self, session_id: str) -> float:
        db = get_db_session()
        try:
            s = db.query(LiveSession).filter(LiveSession.session_id == session_id).first()
            if not s or not s.start_time:
                return 2.0
            end = s.end_time or datetime.now()
            return max((end - s.start_time).total_seconds() / 3600, 0.5)
        finally:
            db.close()

    def _generate_restock_plan(self, product: Product, quantity: int) -> Dict:
        db = get_db_session()
        try:
            supplier = (
                db.query(Supplier).filter(Supplier.supplier_id == product.supplier_id).first()
            )
            if not supplier:
                return {
                    "supplier_id": product.supplier_id or "SUP001",
                    "supplier_name": product.supplier_name or "默认供应商",
                    "delivery_days": product.logistics_days or 3,
                    "estimated_cost": quantity * product.cost_price,
                    "notes": "系统推荐：按历史供应商补货",
                }

            estimated_cost = quantity * product.cost_price + supplier.logistics_fee
            notes = (
                f"推荐供应商: {supplier.name}, "
                f"平均到货: {supplier.average_delivery_days}天, "
                f"可靠度: {supplier.reliability_score * 100:.0f}%, "
                f"物流费: ¥{supplier.logistics_fee:.2f}"
            )
            return {
                "supplier_id": supplier.supplier_id,
                "supplier_name": supplier.name,
                "delivery_days": supplier.average_delivery_days,
                "estimated_cost": estimated_cost,
                "notes": notes,
            }
        finally:
            db.close()

    def push_to_purchase_department(self, alert_id: str) -> bool:
        db = get_db_session()
        try:
            alert = db.query(RestockAlert).filter(RestockAlert.alert_id == alert_id).first()
            if not alert:
                return False
            alert.pushed_to_purchase = True
            alert.pushed_at = datetime.now()
            alert.status = "processing"
            db.commit()
            logger.info(f"补货预警 {alert_id} 已推送采购部门")
            return True
        except Exception as e:
            logger.error(f"推送采购部门失败: {e}")
            db.rollback()
            return False
        finally:
            db.close()


class QualityAlertManager:
    def __init__(self):
        self.industry_avg = settings.INDUSTRY_RETURN_RATE
        self.alert_multiplier = settings.RETURN_RATE_ALERT_MULTIPLIER
        self.consecutive_days = settings.RETURN_RATE_ALERT_DAYS

    def check_return_rates(self) -> List[Dict]:
        db = get_db_session()
        alerts = []
        try:
            products_with_orders = (
                db.query(Order.product_sku).filter(
                    Order.order_time >= datetime.now() - timedelta(days=self.consecutive_days)
                )
                .distinct()
                .all()
            )

            for (sku,) in products_with_orders:
                trend = AnalyticsEngine.get_product_return_trend(sku, days=self.consecutive_days + 7)
                if trend.empty:
                    continue

                recent = trend.tail(self.consecutive_days)
                if len(recent) < self.consecutive_days:
                    continue

                threshold = self.industry_avg * self.alert_multiplier
                all_high = all(r["return_rate"] > threshold for _, r in recent.iterrows())
                avg_return = recent["return_rate"].mean()

                if all_high and avg_return > threshold:
                    product = db.query(Product).filter(Product.sku == sku).first()
                    if not product:
                        continue

                    existing = (
                        db.query(QualityAlert)
                        .filter(
                            and_(
                                QualityAlert.product_sku == sku,
                                QualityAlert.created_at >= datetime.now() - timedelta(hours=12),
                            )
                        )
                        .first()
                    )
                    if existing:
                        continue

                    suggestion = self._generate_suggestion(avg_return, sku, product)
                    alert = QualityAlert(
                        alert_id=f"QA_{uuid.uuid4().hex[:12]}",
                        product_sku=sku,
                        product_name=product.name,
                        return_rate=round(float(avg_return), 4),
                        industry_avg_rate=round(self.industry_avg, 4),
                        consecutive_days=self.consecutive_days,
                        suggestion=suggestion,
                        status="pending",
                        notified_quality=False,
                        promotion_suspended=False,
                    )
                    db.add(alert)
                    db.flush()

                    alerts.append({
                        "alert_id": alert.alert_id,
                        "product_sku": sku,
                        "product_name": product.name,
                        "return_rate": float(avg_return),
                        "industry_avg": self.industry_avg,
                        "consecutive_days": self.consecutive_days,
                        "suggestion": suggestion,
                    })

            db.commit()
            if alerts:
                logger.info(f"生成 {len(alerts)} 条品质预警")
            return alerts
        except Exception as e:
            logger.error(f"检查退货率失败: {e}")
            db.rollback()
            return []
        finally:
            db.close()

    def _generate_suggestion(self, avg_return: float, sku: str, product: Product) -> str:
        over_ratio = (avg_return - self.industry_avg) / self.industry_avg * 100
        suggestions = [
            f"退货率连续{self.consecutive_days}天超行业均值{over_ratio:.1f}%",
            f"建议品控部门介入核查商品质量",
            "建议立即暂停该商品所有推广活动",
            "建议联系供应商协商退换货及后续供货质量问题",
            f"当前商品: {product.name} (SKU: {sku})",
        ]
        return "；".join(suggestions)

    def notify_quality_department(self, alert_id: str) -> bool:
        db = get_db_session()
        try:
            alert = db.query(QualityAlert).filter(QualityAlert.alert_id == alert_id).first()
            if not alert:
                return False
            alert.notified_quality = True
            alert.notified_at = datetime.now()
            alert.status = "notified"
            db.commit()
            logger.info(f"品质预警 {alert_id} 已通知品控部门")
            return True
        except Exception as e:
            logger.error(f"通知品控失败: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def suspend_promotion(self, alert_id: str) -> bool:
        db = get_db_session()
        try:
            alert = db.query(QualityAlert).filter(QualityAlert.alert_id == alert_id).first()
            if not alert:
                return False
            alert.promotion_suspended = True
            alert.status = "suspended"
            db.commit()
            logger.info(f"商品 {alert.product_sku} 推广已暂停")
            return True
        except Exception as e:
            logger.error(f"暂停推广失败: {e}")
            db.rollback()
            return False
        finally:
            db.close()


class PerformanceEvaluator:
    GMV_WEIGHT = 0.40
    INTERACTION_WEIGHT = 0.25
    CONVERSION_WEIGHT = 0.25
    RETURN_WEIGHT = 0.10

    def evaluate_session(self, session_id: str) -> Optional[Dict]:
        db = get_db_session()
        try:
            session = db.query(LiveSession).filter(LiveSession.session_id == session_id).first()
            if not session:
                return None

            anchor = db.query(Anchor).filter(Anchor.anchor_id == session.anchor_id).first()
            if not anchor:
                return None

            existing = (
                db.query(AnchorPerformance)
                .filter(
                    and_(
                        AnchorPerformance.session_id == session_id,
                        AnchorPerformance.anchor_id == session.anchor_id,
                    )
                )
                .first()
            )
            if existing:
                return self._perf_to_dict(existing)

            gmv_rank, gmv_score = self._rank_gmv(session.total_gmv or 0, session.platform)
            interaction_rank, interaction_score = self._rank_interaction_rate(
                session.interaction_rate or 0
            )
            conversion_rank, conversion_score = self._rank_conversion_rate(
                session.click_conversion_rate or 0
            )
            return_rank, return_score = self._rank_return_rate(session.return_rate or 0)

            total_score = round(
                gmv_score * self.GMV_WEIGHT
                + interaction_score * self.INTERACTION_WEIGHT
                + conversion_score * self.CONVERSION_WEIGHT
                + return_score * self.RETURN_WEIGHT,
                2,
            )
            total_rank = self._score_to_rank(total_score)

            history_avg = self._get_history_avg(session.anchor_id, session_id)
            compared = round((total_score - history_avg) / max(history_avg, 1) * 100, 2)

            suggestion = self._generate_suggestion(
                total_rank,
                compared,
                {
                    "gmv_rank": gmv_rank,
                    "interaction_rank": interaction_rank,
                    "conversion_rank": conversion_rank,
                    "return_rank": return_rank,
                },
            )

            perf = AnchorPerformance(
                perf_id=f"PF_{uuid.uuid4().hex[:12]}",
                anchor_id=session.anchor_id,
                session_id=session_id,
                performance_date=session.start_time.date(),
                gmv=round(session.total_gmv or 0, 2),
                gmv_rank=gmv_rank,
                interaction_rate=round(session.interaction_rate or 0, 4),
                interaction_rank=interaction_rank,
                conversion_rate=round(session.click_conversion_rate or 0, 4),
                conversion_rank=conversion_rank,
                return_rate=round(session.return_rate or 0, 4),
                return_rank=return_rank,
                total_score=total_score,
                total_rank=total_rank,
                suggestion=suggestion,
                is_promotion_candidate=total_rank in ["A", "S"] and compared > 5,
                is_improvement_needed=total_rank in ["C", "D"] or compared < -10,
                pushed_to_supervisor=False,
                compared_to_history=compared,
            )
            db.add(perf)

            anchor.performance_score = total_score
            anchor.performance_level = total_rank
            db.commit()

            return self._perf_to_dict(perf)
        except Exception as e:
            logger.error(f"评估主播绩效失败: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    def _rank_gmv(self, gmv: float, platform: str) -> Tuple[str, float]:
        platform_factor = {"抖音": 1.0, "快手": 0.9, "淘宝直播": 1.2, "视频号": 0.6, "B站直播": 0.7}
        adjusted = gmv / platform_factor.get(platform, 1.0)
        if adjusted >= 1000000:
            return "S", 95
        elif adjusted >= 500000:
            return "A", 85
        elif adjusted >= 200000:
            return "B", 75
        elif adjusted >= 50000:
            return "C", 60
        else:
            return "D", 40

    def _rank_interaction_rate(self, rate: float) -> Tuple[str, float]:
        if rate >= 0.15:
            return "S", 95
        elif rate >= 0.10:
            return "A", 85
        elif rate >= 0.05:
            return "B", 75
        elif rate >= 0.02:
            return "C", 60
        else:
            return "D", 40

    def _rank_conversion_rate(self, rate: float) -> Tuple[str, float]:
        if rate >= 0.10:
            return "S", 95
        elif rate >= 0.06:
            return "A", 85
        elif rate >= 0.03:
            return "B", 75
        elif rate >= 0.01:
            return "C", 60
        else:
            return "D", 40

    def _rank_return_rate(self, rate: float) -> Tuple[str, float]:
        if rate <= 0.03:
            return "S", 95
        elif rate <= 0.06:
            return "A", 85
        elif rate <= 0.10:
            return "B", 75
        elif rate <= 0.15:
            return "C", 60
        else:
            return "D", 40

    def _score_to_rank(self, score: float) -> str:
        if score >= 90:
            return "S"
        elif score >= 80:
            return "A"
        elif score >= 70:
            return "B"
        elif score >= 60:
            return "C"
        else:
            return "D"

    def _get_history_avg(self, anchor_id: str, exclude_session_id: str) -> float:
        db = get_db_session()
        try:
            perfs = (
                db.query(AnchorPerformance)
                .filter(
                    and_(
                        AnchorPerformance.anchor_id == anchor_id,
                        AnchorPerformance.session_id != exclude_session_id,
                        AnchorPerformance.performance_date >= date.today() - timedelta(days=90),
                    )
                )
                .all()
            )
            if not perfs:
                return 70.0
            return float(np.mean([p.total_score for p in perfs]))
        finally:
            db.close()

    def _generate_suggestion(self, rank: str, compared: float, ranks: Dict) -> str:
        suggestions = []
        if rank in ["S", "A"]:
            suggestions.append("本场直播表现优秀")
            if compared > 10:
                suggestions.append(f"较历史均值提升{compared:.1f}%，状态出色")
        elif rank == "B":
            suggestions.append("本场直播表现良好，有提升空间")
        elif rank == "C":
            suggestions.append("本场直播表现一般，需要针对性改进")
        else:
            suggestions.append("本场直播表现较差，急需改进")

        weak_points = [k for k, v in ranks.items() if v in ["C", "D"]]
        if weak_points:
            mapping = {
                "gmv_rank": "GMV",
                "interaction_rank": "互动率",
                "conversion_rank": "转化率",
                "return_rank": "退货率",
            }
            suggestions.append(f"需重点提升: {'、'.join(mapping.get(p, p) for p in weak_points)}")

        if compared < -5:
            suggestions.append(f"较历史均值下降{abs(compared):.1f}%，建议复盘问题原因")

        return "；".join(suggestions)

    def _perf_to_dict(self, perf: AnchorPerformance) -> Dict:
        return {
            "perf_id": perf.perf_id,
            "anchor_id": perf.anchor_id,
            "session_id": perf.session_id,
            "total_score": perf.total_score,
            "total_rank": perf.total_rank,
            "gmv_rank": perf.gmv_rank,
            "interaction_rank": perf.interaction_rank,
            "conversion_rank": perf.conversion_rank,
            "return_rank": perf.return_rank,
            "suggestion": perf.suggestion,
            "is_promotion_candidate": perf.is_promotion_candidate,
            "is_improvement_needed": perf.is_improvement_needed,
            "compared_to_history": perf.compared_to_history,
        }

    def push_to_supervisor(self, perf_id: str) -> bool:
        db = get_db_session()
        try:
            perf = db.query(AnchorPerformance).filter(AnchorPerformance.perf_id == perf_id).first()
            if not perf:
                return False
            perf.pushed_to_supervisor = True
            perf.pushed_at = datetime.now()
            db.commit()
            logger.info(f"绩效 {perf_id} 已推送运营主管")
            return True
        except Exception as e:
            logger.error(f"推送运营主管失败: {e}")
            db.rollback()
            return False
        finally:
            db.close()


restock_manager = RestockManager()
quality_alert_manager = QualityAlertManager()
performance_evaluator = PerformanceEvaluator()

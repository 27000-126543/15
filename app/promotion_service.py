import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from sqlalchemy import and_
from app import logger, get_db_session
from app.models import Promotion, PromotionApproval
from config import settings


class PromotionService:
    APPROVAL_THRESHOLD = settings.PROMO_APPROVAL_THRESHOLD

    def create_promotion(
        self,
        name: str,
        promo_type: str,
        budget: float,
        description: str = "",
        min_order_amount: float = 0,
        discount_amount: float = 0,
        discount_percent: float = 0,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        target_user_segment: str = "",
        platform_scope: Optional[List[str]] = None,
        product_scope: Optional[List[str]] = None,
        created_by: str = "system",
    ) -> Optional[Dict]:
        if budget <= 0:
            logger.error("促销活动预算必须大于0")
            return None

        if discount_amount <= 0 and discount_percent <= 0:
            logger.error("必须设置满减金额或折扣比例")
            return None

        db = get_db_session()
        try:
            promo_id = f"PROMO_{uuid.uuid4().hex[:12]}"

            validation_result = self._validate_budget(
                budget, discount_amount, discount_percent, min_order_amount
            )
            if not validation_result["valid"]:
                logger.error(f"预算校验失败: {validation_result['message']}")
                return None

            promotion = Promotion(
                promo_id=promo_id,
                name=name,
                type=promo_type,
                description=description,
                budget=budget,
                remaining_budget=budget,
                min_order_amount=min_order_amount,
                discount_amount=discount_amount,
                discount_percent=discount_percent,
                start_time=start_time,
                end_time=end_time,
                target_user_segment=target_user_segment,
                target_user_count=self._estimate_target_users(target_user_segment),
                platform_scope=platform_scope or [],
                product_scope=product_scope or [],
                status="pending_approval",
                created_by=created_by,
            )
            db.add(promotion)
            db.flush()

            approvals = self._create_approval_chain(db, promo_id, budget)

            db.commit()

            return {
                "promo_id": promo_id,
                "name": name,
                "budget": budget,
                "status": "pending_approval",
                "approvals": [
                    {
                        "level": a.approval_level,
                        "role": a.approval_role,
                        "status": a.status,
                    }
                    for a in approvals
                ],
                "budget_validation": validation_result,
            }
        except Exception as e:
            logger.error(f"创建促销活动失败: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    def _validate_budget(
        self,
        budget: float,
        discount_amount: float,
        discount_percent: float,
        min_order_amount: float,
    ) -> Dict:
        if discount_amount > 0 and min_order_amount <= discount_amount:
            return {
                "valid": False,
                "message": f"满减门槛({min_order_amount})必须大于优惠金额({discount_amount})",
            }

        if discount_percent > 0 and discount_percent >= 1:
            return {"valid": False, "message": "折扣比例必须小于1"}

        if budget < discount_amount * 10:
            return {
                "valid": False,
                "message": f"预算过低，至少应能支持10张优惠券发放 (建议 >= {discount_amount * 10})",
            }

        return {"valid": True, "message": "预算校验通过"}

    def _estimate_target_users(self, segment: str) -> int:
        segments = {
            "all": 1000000,
            "vip": 100000,
            "new": 200000,
            "active": 500000,
            "dormant": 300000,
            "high_value": 50000,
            "": 100000,
        }
        return segments.get(segment, 50000)

    def _create_approval_chain(
        self, db, promo_id: str, budget: float
    ) -> List[PromotionApproval]:
        approvals = []

        approvals.append(
            PromotionApproval(
                approval_id=f"APPR_{uuid.uuid4().hex[:12]}",
                promo_id=promo_id,
                approval_level=1,
                approval_role="运营主管",
                status="pending",
            )
        )

        if budget >= 100000:
            approvals.append(
                PromotionApproval(
                    approval_id=f"APPR_{uuid.uuid4().hex[:12]}",
                    promo_id=promo_id,
                    approval_level=2,
                    approval_role="运营经理",
                    status="pending",
                )
            )

        if budget >= self.APPROVAL_THRESHOLD:
            approvals.append(
                PromotionApproval(
                    approval_id=f"APPR_{uuid.uuid4().hex[:12]}",
                    promo_id=promo_id,
                    approval_level=3,
                    approval_role="运营总监",
                    status="pending",
                )
            )

        for a in approvals:
            db.add(a)
        return approvals

    def approve(
        self,
        promo_id: str,
        approver_id: str,
        approver_name: str,
        level: int,
        comment: str = "",
    ) -> Tuple[bool, str]:
        db = get_db_session()
        try:
            approval = (
                db.query(PromotionApproval)
                .filter(
                    and_(
                        PromotionApproval.promo_id == promo_id,
                        PromotionApproval.approval_level == level,
                    )
                )
                .first()
            )
            if not approval:
                return False, f"未找到第{level}级审批记录"

            if approval.status != "pending":
                return False, f"当前审批状态为: {approval.status}"

            previous = (
                db.query(PromotionApproval)
                .filter(
                    and_(
                        PromotionApproval.promo_id == promo_id,
                        PromotionApproval.approval_level < level,
                    )
                )
                .all()
            )
            if any(p.status != "approved" for p in previous):
                return False, "存在未通过的前置审批"

            approval.status = "approved"
            approval.approver_id = approver_id
            approval.approver_name = approver_name
            approval.comment = comment
            approval.approved_at = datetime.now()
            db.flush()

            remaining = (
                db.query(PromotionApproval)
                .filter(
                    and_(
                        PromotionApproval.promo_id == promo_id,
                        PromotionApproval.status == "pending",
                    )
                )
                .count()
            )

            promotion = db.query(Promotion).filter(Promotion.promo_id == promo_id).first()
            if remaining == 0:
                promotion.status = "active"
                self._launch_targeted_delivery(db, promotion)
                result_msg = f"促销活动 [{promotion.name}] 全部审批通过，已自动投放"
            else:
                promotion.status = f"approved_level_{level}"
                result_msg = f"第{level}级审批通过，等待后续审批 (剩余{remaining}级)"

            promotion.updated_at = datetime.now()
            db.commit()
            logger.info(result_msg)
            return True, result_msg
        except Exception as e:
            logger.error(f"审批失败: {e}")
            db.rollback()
            return False, str(e)
        finally:
            db.close()

    def reject(
        self,
        promo_id: str,
        approver_id: str,
        approver_name: str,
        level: int,
        comment: str = "",
    ) -> Tuple[bool, str]:
        db = get_db_session()
        try:
            approval = (
                db.query(PromotionApproval)
                .filter(
                    and_(
                        PromotionApproval.promo_id == promo_id,
                        PromotionApproval.approval_level == level,
                    )
                )
                .first()
            )
            if not approval:
                return False, f"未找到第{level}级审批记录"

            approval.status = "rejected"
            approval.approver_id = approver_id
            approval.approver_name = approver_name
            approval.comment = comment
            approval.approved_at = datetime.now()

            promotion = db.query(Promotion).filter(Promotion.promo_id == promo_id).first()
            promotion.status = "rejected"
            promotion.updated_at = datetime.now()

            db.commit()
            msg = f"促销活动 [{promotion.name}] 在第{level}级被驳回"
            logger.info(msg)
            return True, msg
        except Exception as e:
            logger.error(f"驳回失败: {e}")
            db.rollback()
            return False, str(e)
        finally:
            db.close()

    def _launch_targeted_delivery(self, db, promotion: Promotion):
        logger.info(
            f"开始向目标用户精准投放促销 [{promotion.promo_id}] "
            f"用户群: {promotion.target_user_segment}, "
            f"预计触达: {promotion.target_user_count}人"
        )

    def get_promotion(self, promo_id: str) -> Optional[Dict]:
        db = get_db_session()
        try:
            promo = db.query(Promotion).filter(Promotion.promo_id == promo_id).first()
            if not promo:
                return None
            approvals = (
                db.query(PromotionApproval)
                .filter(PromotionApproval.promo_id == promo_id)
                .order_by(PromotionApproval.approval_level)
                .all()
            )
            return {
                "promo_id": promo.promo_id,
                "name": promo.name,
                "type": promo.type,
                "description": promo.description,
                "budget": promo.budget,
                "used_budget": promo.used_budget,
                "remaining_budget": promo.remaining_budget,
                "min_order_amount": promo.min_order_amount,
                "discount_amount": promo.discount_amount,
                "discount_percent": promo.discount_percent,
                "start_time": promo.start_time,
                "end_time": promo.end_time,
                "target_user_segment": promo.target_user_segment,
                "target_user_count": promo.target_user_count,
                "platform_scope": promo.platform_scope,
                "product_scope": promo.product_scope,
                "status": promo.status,
                "created_by": promo.created_by,
                "created_at": promo.created_at,
                "approvals": [
                    {
                        "level": a.approval_level,
                        "role": a.approval_role,
                        "status": a.status,
                        "approver": a.approver_name,
                        "comment": a.comment,
                        "approved_at": a.approved_at,
                    }
                    for a in approvals
                ],
            }
        finally:
            db.close()

    def list_promotions(
        self,
        status: Optional[str] = None,
        created_by: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict:
        db = get_db_session()
        try:
            query = db.query(Promotion)
            if status:
                query = query.filter(Promotion.status == status)
            if created_by:
                query = query.filter(Promotion.created_by == created_by)

            total = query.count()
            promotions = query.order_by(Promotion.created_at.desc()).offset(offset).limit(limit).all()

            return {
                "total": total,
                "items": [
                    {
                        "promo_id": p.promo_id,
                        "name": p.name,
                        "type": p.type,
                        "budget": p.budget,
                        "status": p.status,
                        "created_by": p.created_by,
                        "created_at": p.created_at,
                    }
                    for p in promotions
                ],
            }
        finally:
            db.close()

    def cancel_promotion(self, promo_id: str, operator: str = "system") -> Tuple[bool, str]:
        db = get_db_session()
        try:
            promo = db.query(Promotion).filter(Promotion.promo_id == promo_id).first()
            if not promo:
                return False, "促销活动不存在"
            if promo.status == "cancelled":
                return False, "促销活动已取消"
            promo.status = "cancelled"
            promo.updated_at = datetime.now()
            db.commit()
            msg = f"促销活动 [{promo.name}] 已被 {operator} 取消"
            logger.info(msg)
            return True, msg
        except Exception as e:
            logger.error(f"取消促销失败: {e}")
            db.rollback()
            return False, str(e)
        finally:
            db.close()


promotion_service = PromotionService()

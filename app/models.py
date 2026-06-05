from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Date, Boolean,
    ForeignKey, Text, JSON, BigInteger, Index
)
from sqlalchemy.orm import relationship
from app import Base


class Anchor(Base):
    __tablename__ = "anchors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    anchor_id = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    platform = Column(String(32), nullable=False, index=True)
    follower_count = Column(BigInteger, default=0)
    level = Column(String(32), default="普通")
    commission_rate = Column(Float, default=0.20)
    base_salary = Column(Float, default=0.0)
    phone = Column(String(32))
    email = Column(String(128))
    status = Column(String(16), default="active")
    join_date = Column(Date, default=date.today)
    performance_score = Column(Float, default=0.0)
    performance_level = Column(String(16), default="C")
    extra = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    live_sessions = relationship("LiveSession", back_populates="anchor")
    performances = relationship("AnchorPerformance", back_populates="anchor")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(256), nullable=False, index=True)
    category = Column(String(64), index=True)
    brand = Column(String(128))
    cost_price = Column(Float, nullable=False)
    sale_price = Column(Float, nullable=False)
    original_stock = Column(Integer, default=0)
    current_stock = Column(Integer, default=0)
    safety_stock = Column(Integer, default=100)
    supplier_id = Column(String(64), index=True)
    supplier_name = Column(String(256))
    logistics_days = Column(Integer, default=3)
    main_image = Column(String(512))
    status = Column(String(16), default="active")
    extra = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    live_products = relationship("LiveProduct", back_populates="product")


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_id = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(256), nullable=False)
    contact = Column(String(64))
    phone = Column(String(32))
    address = Column(String(512))
    logistics_fee = Column(Float, default=0.0)
    average_delivery_days = Column(Integer, default=3)
    reliability_score = Column(Float, default=0.8)
    status = Column(String(16), default="active")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class LiveSession(Base):
    __tablename__ = "live_sessions"
    __table_args__ = (
        Index("idx_platform_start", "platform", "start_time"),
        Index("idx_anchor_time", "anchor_id", "start_time"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), unique=True, index=True, nullable=False)
    anchor_id = Column(String(64), ForeignKey("anchors.anchor_id"), index=True)
    platform = Column(String(32), nullable=False, index=True)
    title = Column(String(256))
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime)
    status = Column(String(16), default="scheduled")
    estimated_traffic = Column(BigInteger, default=0)
    estimated_subsidy = Column(Float, default=0.0)
    estimated_gmv = Column(Float, default=0.0)
    target_gmv = Column(Float, default=0.0)
    actual_traffic = Column(BigInteger, default=0)
    actual_subsidy = Column(Float, default=0.0)
    peak_viewers = Column(Integer, default=0)
    avg_viewers = Column(Integer, default=0)
    total_viewers = Column(BigInteger, default=0)
    interaction_count = Column(BigInteger, default=0)
    interaction_rate = Column(Float, default=0.0)
    click_count = Column(BigInteger, default=0)
    click_conversion_rate = Column(Float, default=0.0)
    total_orders = Column(Integer, default=0)
    paid_orders = Column(Integer, default=0)
    total_gmv = Column(Float, default=0.0)
    total_profit = Column(Float, default=0.0)
    return_count = Column(Integer, default=0)
    return_amount = Column(Float, default=0.0)
    return_rate = Column(Float, default=0.0)
    traffic_cost = Column(Float, default=0.0)
    roi = Column(Float, default=0.0)
    gmv_achievement_rate = Column(Float, default=0.0)
    extra = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    anchor = relationship("Anchor", back_populates="live_sessions")
    products = relationship("LiveProduct", back_populates="live_session")
    orders = relationship("Order", back_populates="live_session")
    performances = relationship("AnchorPerformance", back_populates="live_session")
    data_points = relationship("RealtimeDataPoint", back_populates="live_session")


class LiveProduct(Base):
    __tablename__ = "live_products"
    __table_args__ = (
        Index("idx_session_product", "session_id", "product_sku"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("live_sessions.session_id"), index=True)
    product_sku = Column(String(64), ForeignKey("products.sku"), index=True)
    sequence = Column(Integer, default=0)
    on_shelf_time = Column(DateTime)
    off_shelf_time = Column(DateTime)
    live_price = Column(Float, default=0.0)
    live_stock = Column(Integer, default=0)
    sold_quantity = Column(Integer, default=0)
    sold_amount = Column(Float, default=0.0)
    click_count = Column(Integer, default=0)
    conversion_rate = Column(Float, default=0.0)
    return_count = Column(Integer, default=0)
    return_rate = Column(Float, default=0.0)
    profit = Column(Float, default=0.0)
    sell_out_rate = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    live_session = relationship("LiveSession", back_populates="products")
    product = relationship("Product", back_populates="live_products")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("idx_session_status", "session_id", "status"),
        Index("idx_order_time", "order_time"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), unique=True, index=True, nullable=False)
    session_id = Column(String(64), ForeignKey("live_sessions.session_id"), index=True)
    product_sku = Column(String(64), index=True)
    anchor_id = Column(String(64), index=True)
    platform = Column(String(32), index=True)
    user_id = Column(String(128))
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, default=0.0)
    total_amount = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    paid_amount = Column(Float, default=0.0)
    cost_amount = Column(Float, default=0.0)
    profit = Column(Float, default=0.0)
    status = Column(String(16), default="pending")
    order_time = Column(DateTime, default=datetime.now, index=True)
    paid_time = Column(DateTime)
    shipped_time = Column(DateTime)
    returned_time = Column(DateTime)
    return_reason = Column(String(256))
    promotion_id = Column(String(64))
    extra = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.now)

    live_session = relationship("LiveSession", back_populates="orders")


class RealtimeDataPoint(Base):
    __tablename__ = "realtime_data_points"
    __table_args__ = (
        Index("idx_session_time", "session_id", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("live_sessions.session_id"), index=True)
    timestamp = Column(DateTime, default=datetime.now, index=True)
    viewer_count = Column(Integer, default=0)
    new_viewers = Column(Integer, default=0)
    interaction_count = Column(Integer, default=0)
    click_count = Column(Integer, default=0)
    order_count = Column(Integer, default=0)
    gmv = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)

    live_session = relationship("LiveSession", back_populates="data_points")


class RestockAlert(Base):
    __tablename__ = "restock_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(String(64), unique=True, index=True, nullable=False)
    product_sku = Column(String(64), index=True, nullable=False)
    product_name = Column(String(256))
    session_id = Column(String(64), index=True)
    current_stock = Column(Integer, default=0)
    original_stock = Column(Integer, default=0)
    sell_out_rate = Column(Float, default=0.0)
    suggested_quantity = Column(Integer, default=0)
    supplier_id = Column(String(64))
    supplier_name = Column(String(256))
    estimated_delivery_days = Column(Integer, default=3)
    estimated_cost = Column(Float, default=0.0)
    priority = Column(String(16), default="normal")
    status = Column(String(16), default="pending")
    pushed_to_purchase = Column(Boolean, default=False)
    pushed_at = Column(DateTime)
    purchase_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class QualityAlert(Base):
    __tablename__ = "quality_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(String(64), unique=True, index=True, nullable=False)
    product_sku = Column(String(64), index=True, nullable=False)
    product_name = Column(String(256))
    anchor_id = Column(String(64))
    return_rate = Column(Float, default=0.0)
    industry_avg_rate = Column(Float, default=0.0)
    consecutive_days = Column(Integer, default=0)
    suggestion = Column(String(256))
    status = Column(String(16), default="pending")
    notified_quality = Column(Boolean, default=False)
    notified_at = Column(DateTime)
    promotion_suspended = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AnchorPerformance(Base):
    __tablename__ = "anchor_performances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    perf_id = Column(String(64), unique=True, index=True, nullable=False)
    anchor_id = Column(String(64), ForeignKey("anchors.anchor_id"), index=True)
    session_id = Column(String(64), ForeignKey("live_sessions.session_id"), index=True)
    performance_date = Column(Date, index=True)
    gmv = Column(Float, default=0.0)
    gmv_rank = Column(String(8), default="C")
    interaction_rate = Column(Float, default=0.0)
    interaction_rank = Column(String(8), default="C")
    conversion_rate = Column(Float, default=0.0)
    conversion_rank = Column(String(8), default="C")
    return_rate = Column(Float, default=0.0)
    return_rank = Column(String(8), default="C")
    total_score = Column(Float, default=0.0)
    total_rank = Column(String(8), default="C")
    suggestion = Column(Text)
    is_promotion_candidate = Column(Boolean, default=False)
    is_improvement_needed = Column(Boolean, default=False)
    pushed_to_supervisor = Column(Boolean, default=False)
    pushed_at = Column(DateTime)
    compared_to_history = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)

    anchor = relationship("Anchor", back_populates="performances")
    live_session = relationship("LiveSession", back_populates="performances")


class Promotion(Base):
    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    promo_id = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(256), nullable=False)
    type = Column(String(32), default="coupon")
    description = Column(Text)
    budget = Column(Float, nullable=False)
    used_budget = Column(Float, default=0.0)
    remaining_budget = Column(Float, default=0.0)
    min_order_amount = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    discount_percent = Column(Float, default=0.0)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    target_user_segment = Column(String(64))
    target_user_count = Column(Integer, default=0)
    platform_scope = Column(JSON, default=list)
    product_scope = Column(JSON, default=list)
    status = Column(String(16), default="draft")
    created_by = Column(String(64))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    approvals = relationship("PromotionApproval", back_populates="promotion")


class PromotionApproval(Base):
    __tablename__ = "promotion_approvals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    approval_id = Column(String(64), unique=True, index=True, nullable=False)
    promo_id = Column(String(64), ForeignKey("promotions.promo_id"), index=True)
    approval_level = Column(Integer, default=1)
    approval_role = Column(String(32), default="运营主管")
    approver_id = Column(String(64))
    approver_name = Column(String(128))
    status = Column(String(16), default="pending")
    comment = Column(Text)
    approved_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

    promotion = relationship("Promotion", back_populates="approvals")


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(String(64), unique=True, index=True, nullable=False)
    report_date = Column(Date, unique=True, index=True)
    total_gmv = Column(Float, default=0.0)
    total_orders = Column(Integer, default=0)
    total_traffic_cost = Column(Float, default=0.0)
    total_profit = Column(Float, default=0.0)
    total_return_amount = Column(Float, default=0.0)
    overall_roi = Column(Float, default=0.0)
    platform_summary = Column(JSON, default=dict)
    anchor_summary = Column(JSON, default=list)
    product_top10 = Column(JSON, default=list)
    gmv_trend_7d = Column(JSON, default=list)
    gmv_trend_30d = Column(JSON, default=list)
    alerts_count = Column(Integer, default=0)
    promotions_active = Column(Integer, default=0)
    pdf_path = Column(String(512))
    excel_path = Column(String(512))
    generated_at = Column(DateTime, default=datetime.now)
    generated_by = Column(String(64), default="system")


class OperationLog(Base):
    __tablename__ = "operation_logs"
    __table_args__ = (
        Index("idx_user_time", "user_id", "created_at"),
        Index("idx_module_action", "module", "action"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    log_id = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(String(64), index=True)
    user_name = Column(String(128))
    role = Column(String(32))
    module = Column(String(64), index=True)
    action = Column(String(32), index=True)
    target_type = Column(String(64))
    target_id = Column(String(64))
    description = Column(Text)
    request_ip = Column(String(64))
    user_agent = Column(String(512))
    before_data = Column(JSON)
    after_data = Column(JSON)
    status = Column(String(16), default="success")
    error_msg = Column(Text)
    created_at = Column(DateTime, default=datetime.now, index=True)


def init_db():
    from app import engine
    Base.metadata.create_all(bind=engine)

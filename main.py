import os
import sys
import uuid
import random
import threading
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Depends, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler

from config import settings, BASE_DIR
from app import logger, get_db, engine
from app.models import init_db, LiveSession, Anchor, Product
from app.data_crawlers import crawler_manager
from app.analytics_engine import LiveSessionAnalyzer, AnalyticsEngine
from app.decision_engine import (
    restock_manager, quality_alert_manager, performance_evaluator
)
from app.promotion_service import promotion_service
from app.report_generator import daily_report_generator
from app.query_export import query_service, batch_exporter
from app.logging_concurrency import (
    operation_logger, log_operation, concurrency_limiter, rate_limiter
)


scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def schedule_daily_tasks(generate_report: bool = True):
    for d in range(1, 8):
        target_date = date.today() - timedelta(days=d)
        crawler_manager.crawl_all_sessions(target_date)
        sessions = []
        db = next(get_db())
        try:
            sessions = db.query(LiveSession).filter(
                LiveSession.start_time >= datetime.combine(target_date, datetime.min.time()),
                LiveSession.start_time <= datetime.combine(target_date, datetime.max.time()),
            ).all()
        finally:
            db.close()
        for s in sessions:
            for _ in range(random.randint(5, 30)):
                crawler_manager.collect_realtime_data(s.session_id, s.platform)
            crawler_manager.collect_orders(s.session_id, s.platform)
            analyzer = LiveSessionAnalyzer(s.session_id)
            analyzer.compute_session_metrics()
            analyzer.compute_product_metrics()
            analyzer.close()
            restock_manager.check_and_generate_alerts(s.session_id)
            performance_evaluator.evaluate_session(s.session_id)
    quality_alert_manager.check_return_rates()
    if generate_report:
        try:
            daily_report_generator.generate()
        except Exception as e:
            logger.warning(f"日报生成失败（不阻塞服务）: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"启动 {settings.APP_NAME}...")
    init_db()
    logger.info("数据库初始化完成")

    if not scheduler.running:
        scheduler.add_job(
            schedule_daily_tasks,
            "cron",
            hour=settings.DAILY_REPORT_HOUR,
            minute=settings.DAILY_REPORT_MINUTE,
            id="daily_operation",
            replace_existing=True,
        )
        scheduler.start()
        logger.info(
            f"定时任务已启动: 每日 {settings.DAILY_REPORT_HOUR:02d}:{settings.DAILY_REPORT_MINUTE:02d} 执行日报生成"
        )

    if os.environ.get("INIT_SAMPLE_DATA", "1") == "1":
        def _init_background():
            logger.info("开始后台初始化示例数据...")
            try:
                schedule_daily_tasks(generate_report=False)
                logger.info("示例数据初始化完成")
            except Exception as e:
                logger.error(f"初始化示例数据失败: {e}")

        threading.Thread(target=_init_background, daemon=True).start()
        logger.info("示例数据初始化任务已在后台启动")

    yield

    if scheduler.running:
        scheduler.shutdown()
        logger.info("调度器已关闭")
    operation_logger.force_flush()
    logger.info("系统已安全关闭")


app = FastAPI(
    title=settings.APP_NAME,
    description="企业级多平台直播运营数据自动化汇聚与智能决策管理系统",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "version": "2.0.0",
        "status": "running",
        "time": datetime.now().isoformat(),
        "platforms": settings.PLATFORMS,
    }


@app.get("/api/v1/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post("/api/v1/crawl/all")
@log_operation(module="数据采集", action="全量抓取", description="触发全平台直播数据采集")
async def trigger_crawl_all(target_date: Optional[date] = None):
    sessions = crawler_manager.crawl_all_sessions(target_date)
    return {"status": "success", "sessions_count": len(sessions), "sessions": sessions}


@app.post("/api/v1/crawl/realtime/{session_id}")
@log_operation(module="数据采集", action="实时采集", description="采集单场直播实时数据")
async def trigger_realtime_crawl(session_id: str):
    db = next(get_db())
    try:
        session = db.query(LiveSession).filter(LiveSession.session_id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="直播场次不存在")
        data = crawler_manager.collect_realtime_data(session_id, session.platform)
        crawler_manager.collect_orders(session_id, session.platform)
        return {"status": "success", "data": data}
    finally:
        db.close()


@app.post("/api/v1/calc/session/{session_id}")
@log_operation(module="计算引擎", action="指标计算", description="计算直播场次核心指标")
async def calc_session_metrics(session_id: str):
    analyzer = LiveSessionAnalyzer(session_id)
    try:
        metrics = analyzer.compute_session_metrics()
        products = analyzer.compute_product_metrics()
        if not metrics:
            raise HTTPException(status_code=404, detail="直播场次不存在")
        return {
            "status": "success",
            "session_metrics": metrics,
            "product_metrics": products,
        }
    finally:
        analyzer.close()


@app.get("/api/v1/analytics/compare/{session_id}")
async def compare_vs_estimate(session_id: str):
    result = AnalyticsEngine.compare_vs_estimate(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="直播场次不存在")
    return result


@app.get("/api/v1/analytics/platform-summary")
async def get_platform_summary(target_date: Optional[date] = None):
    df = AnalyticsEngine.get_platform_summary(target_date)
    return {"date": str(target_date or date.today()), "data": df.to_dict(orient="records") if not df.empty else []}


@app.get("/api/v1/analytics/anchor-ranking")
async def get_anchor_ranking(target_date: Optional[date] = None, top_n: int = 20):
    df = AnalyticsEngine.get_anchor_ranking(target_date, top_n)
    return {"date": str(target_date or date.today()), "data": df.to_dict(orient="records") if not df.empty else []}


@app.get("/api/v1/analytics/gmv-trend")
async def get_gmv_trend(days: int = 30):
    df = AnalyticsEngine.get_gmv_trend(days)
    return {"data": df.to_dict(orient="records") if not df.empty else []}


@app.post("/api/v1/alerts/restock/check")
@log_operation(module="智能决策", action="补货检查", description="检查并生成补货预警")
async def check_restock_alerts(session_id: Optional[str] = None):
    alerts = restock_manager.check_and_generate_alerts(session_id)
    return {"status": "success", "alerts_count": len(alerts), "alerts": alerts}


@app.post("/api/v1/alerts/restock/{alert_id}/push")
@log_operation(module="智能决策", action="推送采购", description="推送补货建议到采购部门")
async def push_restock_to_purchase(alert_id: str):
    success = restock_manager.push_to_purchase_department(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="补货预警不存在")
    return {"status": "success", "message": "已推送采购部门"}


@app.post("/api/v1/alerts/quality/check")
@log_operation(module="智能决策", action="品质检查", description="检查退货率并生成品质预警")
async def check_quality_alerts():
    alerts = quality_alert_manager.check_return_rates()
    return {"status": "success", "alerts_count": len(alerts), "alerts": alerts}


@app.post("/api/v1/alerts/quality/{alert_id}/notify")
@log_operation(module="智能决策", action="通知品控", description="通知品控部门处理品质预警")
async def notify_quality_dept(alert_id: str):
    success = quality_alert_manager.notify_quality_department(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="品质预警不存在")
    return {"status": "success", "message": "已通知品控部门"}


@app.post("/api/v1/alerts/quality/{alert_id}/suspend")
@log_operation(module="智能决策", action="暂停推广", description="暂停高退货率商品推广")
async def suspend_promotion(alert_id: str):
    success = quality_alert_manager.suspend_promotion(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="品质预警不存在")
    return {"status": "success", "message": "商品推广已暂停"}


@app.post("/api/v1/performance/evaluate/{session_id}")
@log_operation(module="绩效评估", action="评估绩效", description="评估单场直播主播绩效")
async def evaluate_performance(session_id: str):
    result = performance_evaluator.evaluate_session(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="直播场次不存在")
    return {"status": "success", "performance": result}


@app.post("/api/v1/performance/{perf_id}/push")
@log_operation(module="绩效评估", action="推送主管", description="推送绩效结果给运营主管")
async def push_performance_to_supervisor(perf_id: str):
    success = performance_evaluator.push_to_supervisor(perf_id)
    if not success:
        raise HTTPException(status_code=404, detail="绩效记录不存在")
    return {"status": "success", "message": "已推送运营主管"}


@app.post("/api/v1/promotions")
@log_operation(module="促销管理", action="创建活动", description="创建促销活动")
async def create_promotion(
    name: str,
    promo_type: str = Query("coupon", description="促销类型: coupon满减/discount折扣"),
    budget: float = Query(..., gt=0, description="活动预算"),
    description: str = "",
    min_order_amount: float = 0,
    discount_amount: float = 0,
    discount_percent: float = 0,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    target_user_segment: str = "active",
):
    result = promotion_service.create_promotion(
        name=name,
        promo_type=promo_type,
        budget=budget,
        description=description,
        min_order_amount=min_order_amount,
        discount_amount=discount_amount,
        discount_percent=discount_percent,
        start_time=start_time,
        end_time=end_time,
        target_user_segment=target_user_segment,
    )
    if not result:
        raise HTTPException(status_code=400, detail="促销活动创建失败")
    return {"status": "success", "promotion": result}


@app.get("/api/v1/promotions")
async def list_promotions(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    return promotion_service.list_promotions(status=status, limit=limit, offset=offset)


@app.get("/api/v1/promotions/{promo_id}")
async def get_promotion(promo_id: str):
    promo = promotion_service.get_promotion(promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="促销活动不存在")
    return promo


@app.post("/api/v1/promotions/{promo_id}/approve")
@log_operation(module="促销管理", action="审批通过", description="审批促销活动")
async def approve_promotion(
    promo_id: str,
    level: int = Query(..., description="审批级别"),
    approver_id: str = "U001",
    approver_name: str = "审批人",
    comment: str = "",
):
    success, msg = promotion_service.approve(promo_id, approver_id, approver_name, level, comment)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@app.post("/api/v1/promotions/{promo_id}/reject")
@log_operation(module="促销管理", action="审批驳回", description="驳回促销活动")
async def reject_promotion(
    promo_id: str,
    level: int = Query(..., description="审批级别"),
    approver_id: str = "U001",
    approver_name: str = "审批人",
    comment: str = "",
):
    success, msg = promotion_service.reject(promo_id, approver_id, approver_name, level, comment)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@app.post("/api/v1/promotions/{promo_id}/cancel")
@log_operation(module="促销管理", action="取消活动", description="取消促销活动")
async def cancel_promotion(promo_id: str):
    success, msg = promotion_service.cancel_promotion(promo_id)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@app.post("/api/v1/reports/generate")
@log_operation(module="报表中心", action="生成日报", description="生成运营日报")
async def generate_daily_report(target_date: Optional[date] = None):
    report = daily_report_generator.generate(target_date)
    if not report:
        raise HTTPException(status_code=500, detail="日报生成失败")
    return {"status": "success", "report": report}


@app.get("/api/v1/reports/daily")
async def get_daily_report(target_date: Optional[date] = None):
    if not target_date:
        target_date = date.today()
    report = daily_report_generator.get_report(target_date)
    if not report:
        raise HTTPException(status_code=404, detail="日报不存在，请先生成")
    return report


@app.get("/api/v1/reports/daily/{target_date}/download")
async def download_daily_report(target_date: date, format: str = Query("pdf", description="pdf或excel")):
    report = daily_report_generator.get_report(target_date)
    if not report:
        raise HTTPException(status_code=404, detail="日报不存在，请先生成")
    path = report["pdf_path"] if format.lower() == "pdf" else report["excel_path"]
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        path=path,
        filename=os.path.basename(path),
        media_type=(
            "application/pdf"
            if format.lower() == "pdf"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )


@app.get("/api/v1/query/sessions")
async def query_sessions(
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
):
    return query_service.query_live_sessions(
        anchor_id=anchor_id,
        product_sku=product_sku,
        platform=platform,
        start_date=start_date,
        end_date=end_date,
        min_gmv=min_gmv,
        max_gmv=max_gmv,
        status=status,
        limit=limit,
        offset=offset,
    )


@app.get("/api/v1/query/orders")
async def query_orders(
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
):
    return query_service.query_orders(
        session_id=session_id,
        anchor_id=anchor_id,
        product_sku=product_sku,
        platform=platform,
        start_date=start_date,
        end_date=end_date,
        status=status,
        min_amount=min_amount,
        max_amount=max_amount,
        limit=limit,
        offset=offset,
    )


@app.get("/api/v1/query/products")
async def query_products(
    sku: Optional[str] = None,
    name: Optional[str] = None,
    category: Optional[str] = None,
    supplier_id: Optional[str] = None,
    status: Optional[str] = None,
    min_stock: Optional[int] = None,
    max_stock: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
):
    return query_service.query_products(
        sku=sku,
        name=name,
        category=category,
        supplier_id=supplier_id,
        status=status,
        min_stock=min_stock,
        max_stock=max_stock,
        limit=limit,
        offset=offset,
    )


@app.get("/api/v1/query/anchors")
async def query_anchors(
    anchor_id: Optional[str] = None,
    name: Optional[str] = None,
    platform: Optional[str] = None,
    level: Optional[str] = None,
    status: Optional[str] = None,
    min_score: Optional[float] = None,
    limit: int = 100,
    offset: int = 0,
):
    return query_service.query_anchors(
        anchor_id=anchor_id,
        name=name,
        platform=platform,
        level=level,
        status=status,
        min_score=min_score,
        limit=limit,
        offset=offset,
    )


@app.post("/api/v1/export/sessions")
@log_operation(module="数据导出", action="导出直播", description="批量导出直播明细")
async def export_sessions(
    format: str = Query("xlsx", description="xlsx或csv"),
    anchor_id: Optional[str] = None,
    product_sku: Optional[str] = None,
    platform: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    path = batch_exporter.export_live_sessions(
        format=format,
        anchor_id=anchor_id,
        product_sku=product_sku,
        platform=platform,
        start_date=start_date,
        end_date=end_date,
    )
    return {"status": "success", "file_path": path, "download_url": f"/api/v1/download?path={path}"}


@app.post("/api/v1/export/orders")
@log_operation(module="数据导出", action="导出订单", description="批量导出订单明细")
async def export_orders(
    format: str = Query("xlsx", description="xlsx或csv"),
    session_id: Optional[str] = None,
    anchor_id: Optional[str] = None,
    product_sku: Optional[str] = None,
    platform: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    path = batch_exporter.export_orders(
        format=format,
        session_id=session_id,
        anchor_id=anchor_id,
        product_sku=product_sku,
        platform=platform,
        start_date=start_date,
        end_date=end_date,
    )
    return {"status": "success", "file_path": path, "download_url": f"/api/v1/download?path={path}"}


@app.get("/api/v1/download")
async def download_file(path: str):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    if not str(path).startswith(str(BASE_DIR)):
        raise HTTPException(status_code=403, detail="路径不合法")
    return FileResponse(path=path, filename=os.path.basename(path))


@app.get("/api/v1/logs")
async def get_operation_logs(
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
):
    return operation_logger.query_logs(
        user_id=user_id,
        module=module,
        action=action,
        target_type=target_type,
        target_id=target_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )


@app.get("/api/v1/logs/stats")
async def get_log_stats(target_date: Optional[date] = None):
    return operation_logger.get_stats(target_date)


@app.get("/api/v1/system/stats")
async def system_stats():
    db = next(get_db())
    try:
        return {
            "timestamp": datetime.now().isoformat(),
            "anchors_count": db.query(Anchor).count(),
            "products_count": db.query(Product).count(),
            "sessions_count": db.query(LiveSession).count(),
            "active_concurrent": concurrency_limiter.active_count,
            "scheduler_running": scheduler.running,
            "platforms": settings.PLATFORMS,
        }
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=4,
    )

import sys
sys.path.insert(0, '.')
from app import get_db_session
from app.models import LiveSession, Order, Anchor
from datetime import datetime, date, timedelta
from sqlalchemy import func

db = get_db_session()
today = date.today()
start = datetime.combine(today, datetime.min.time())
end = start + timedelta(days=1)
print("=== 数据库内容检查 ===")
print(f"今天日期: {today}")
print(f"查询范围: {start} ~ {end}")

all_sessions = db.query(LiveSession).all()
print(f"所有直播场次总数: {len(all_sessions)}")

print("\n前5场直播详情:")
for s in all_sessions[:5]:
    print(f"  [{s.platform}] {s.session_id}")
    print(f"    start_time={s.start_time}, status={s.status}")
    print(f"    total_gmv={s.total_gmv}, total_viewers={s.total_viewers}, total_orders={s.total_orders}")
    print(f"    estimated_gmv={s.estimated_gmv}, target_gmv={s.target_gmv}")

today_sessions = db.query(LiveSession).filter(
    LiveSession.start_time >= start,
    LiveSession.start_time < end,
).all()
print(f"\n今天的直播场次数 (按start_time过滤): {len(today_sessions)}")

orders_count = db.query(Order).count()
print(f"\n订单总数: {orders_count}")
if orders_count > 0:
    print("前3条订单:")
    for o in db.query(Order).limit(3).all():
        print(f"  {o.order_id}: session={o.session_id}, sku={o.product_sku}")
        print(f"    qty={o.quantity}, paid={o.paid_amount}, status={o.status}, order_time={o.order_time}")

anchors_count = db.query(Anchor).count()
print(f"\n主播总数: {anchors_count}")

print("\n=== 测试Worker同款查询 ===")
target_date = today
start_dt = datetime.combine(target_date, datetime.min.time())
end_dt = start_dt + timedelta(days=1)
print(f"start_dt={start_dt}, end_dt={end_dt}")

sessions = db.query(LiveSession).filter(
    LiveSession.start_time >= start_dt,
    LiveSession.start_time < end_dt,
).all()
print(f"Worker查到场次: {len(sessions)}")

session_ids = [s.id for s in sessions]
session_str_ids = [s.session_id for s in sessions]
print(f"id list (数字): {session_ids[:5]}")
print(f"session_id list (字符串): {session_str_ids[:5]}")

if sessions:
    print("\n场次的total_gmv:")
    for s in sessions:
        print(f"  {s.session_id}: total_gmv={s.total_gmv}, total_viewers={s.total_viewers}")

    total_gmv = db.query(func.coalesce(func.sum(LiveSession.total_gmv), 0)).filter(
        LiveSession.id.in_(session_ids)
    ).scalar()
    print(f"\nSUM(total_gmv) via id.in_: {total_gmv}")

    # 直接从sessions列表计算
    direct_sum = sum(s.total_gmv or 0 for s in sessions)
    print(f"SUM(total_gmv) via Python loop: {direct_sum}")

    # 查订单
    if session_str_ids:
        orders = db.query(Order).filter(Order.session_id.in_(session_str_ids)).all()
        print(f"订单数量 (session_id字符串过滤): {len(orders)}")
        paid_sum = db.query(func.coalesce(func.sum(Order.paid_amount), 0)).filter(
            Order.session_id.in_(session_str_ids)
        ).scalar()
        print(f"订单paid_amount总和: {paid_sum}")

db.close()
print("\n=== 检查完成 ===")

import urllib.parse, urllib.request, json

def api_get(path):
    with urllib.request.urlopen(f"http://127.0.0.1:8000{path}") as resp:
        return json.loads(resp.read().decode())

def api_post(path, params=None):
    url = f"http://127.0.0.1:8000{path}"
    if params:
        url += f"?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

print("=" * 60)
print("  API 功能测试报告")
print("=" * 60)

# 1. 根路径
print("\n[1] 根路径 /")
r = api_get("/")
print(f"  ✓ {r['app']} v{r['version']} - {r['status']}")

# 2. 健康检查
print("\n[2] 健康检查 /api/v1/health")
r = api_get("/api/v1/health")
print(f"  ✓ {r['status']}")

# 3. 数据采集
print("\n[3] 全平台数据采集 POST /api/v1/crawl/all")
r = api_post("/api/v1/crawl/all")
print(f"  ✓ 采集成功，{r['sessions_count']} 场直播")

# 4. 创建促销
print("\n[4] 创建促销 POST /api/v1/promotions")
r = api_post("/api/v1/promotions", {
    "name": "API测试大促",
    "budget": 600000,
    "promo_type": "coupon",
    "min_order_amount": 300,
    "discount_amount": 50,
})
promo_id = r["promotion"]["promo_id"]
print(f"  ✓ 创建成功 {promo_id}")
print(f"    预算校验: {r['promotion']['budget_validation']['message']}")
print(f"    审批链: {' -> '.join(a['role'] for a in r['promotion']['approvals'])}")

# 5. 查询促销
print("\n[5] 查询促销列表 GET /api/v1/promotions")
r = api_get("/api/v1/promotions")
print(f"  ✓ 共 {r['total']} 个促销活动")

# 6. 第1级审批
print("\n[6] 第1级审批 POST /api/v1/promotions/{id}/approve")
r = api_post(f"/api/v1/promotions/{promo_id}/approve", {
    "user_id": "U001", "user_name": "张主管",
    "level": 1, "comment": "同意",
})
print(f"  ✓ {r['message']}")

# 7. 第2级审批
print("\n[7] 第2级审批 POST /api/v1/promotions/{id}/approve")
r = api_post(f"/api/v1/promotions/{promo_id}/approve", {
    "user_id": "U002", "user_name": "李经理",
    "level": 2, "comment": "预算合理",
})
print(f"  ✓ {r['message']}")

# 8. 第3级审批
print("\n[8] 第3级审批 POST /api/v1/promotions/{id}/approve")
r = api_post(f"/api/v1/promotions/{promo_id}/approve", {
    "user_id": "U003", "user_name": "王总监",
    "level": 3, "comment": "批准执行",
})
print(f"  ✓ {r['message']}")

# 9. 查询直播
print("\n[9] 查询直播场次 GET /api/v1/query/sessions")
r = api_get("/api/v1/query/sessions?limit=5")
print(f"  ✓ 共 {r['total']} 场直播，展示前3场:")
for s in r["items"][:3]:
    print(f"    {s['platform']} | {s['anchor_name']} | GMV=¥{s.get('total_gmv',0):,.0f}")

# 10. 系统状态
print("\n[10] 系统状态 GET /api/v1/system/stats")
r = api_get("/api/v1/system/stats")
print(f"  ✓ 主播数: {r['anchors_count']}")
print(f"    商品数: {r['products_count']}")
print(f"    直播场次: {r['sessions_count']}")
print(f"    调度器: {'运行中' if r['scheduler_running'] else '已停止'}")

# 11. 日志统计
print("\n[11] 操作日志统计 GET /api/v1/logs/stats")
r = api_get("/api/v1/logs/stats")
print(f"  ✓ 今日操作: {r['total_operations']} 次")
if r['by_module']:
    print(f"    模块分布: {r['by_module']}")

print("\n" + "=" * 60)
print("  所有 API 测试通过！系统运行正常 ✓")
print("=" * 60)

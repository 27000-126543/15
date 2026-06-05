import requests
import json

print("=" * 60)
print("生产级改造验证测试")
print("=" * 60)

print("\n[1] 系统状态 (新增数据库/缓存/爬虫配置)")
r = requests.get("http://127.0.0.1:8000/api/v1/system/stats")
print(f"    Status: {r.status_code}")
d = r.json()
print(f"    数据库引擎: {d['database']['engine']}")
print(f"    数据库连接: {'✓ OK' if d['database']['connected'] else '✗ FAIL'}")
print(f"    缓存: Redis={d['cache']['enabled']}, 本地缓存={d['cache']['local_cache_size']} 条")
print(f"    Worker隔离: {d['reporting']['isolated_worker']}")
print("    平台爬虫状态:")
for p, s in d["crawlers"].items():
    mode = "真实API" if s["api_enabled"] else "Mock"
    print(f"      {p}: {mode}, base={s['base_url']}, token={'✓' if s['has_token'] else '✗'}")

print("\n[2] 健康检查")
r = requests.get("http://127.0.0.1:8000/api/v1/system/health")
print(f"    Status: {r.status_code}")
d = r.json()
print(f"    整体: {d['status']}")
print(f"    数据库: {d['checks']['database']}")
print(f"    缓存: {d['checks']['cache']}")

print("\n[3] 数据采集 (Mock模式)")
r = requests.post("http://127.0.0.1:8000/api/v1/crawl/all")
print(f"    Status: {r.status_code}")
if r.status_code == 200:
    d = r.json()
    print(f"    总场次: {d.get('total_sessions', 0)}")
    for p, cnt in d.get("per_platform", {}).items():
        print(f"      {p}: {cnt} 场")

print("\n[4] 日报生成 (独立Worker进程)")
r = requests.post("http://127.0.0.1:8000/api/v1/reports/generate")
print(f"    Status: {r.status_code}")
if r.status_code == 200:
    d = r.json()
    print(f"    Report ID: {d.get('report_id')}")
    print(f"    Worker生成: {d.get('worker_generated', False)}")
    if d.get("files"):
        for k, v in d["files"].items():
            print(f"      {k}: {v}")

print("\n" + "=" * 60)
print("全部测试完成!")
print("=" * 60)

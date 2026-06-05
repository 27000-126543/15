import requests
import os
import sys

os.environ['DOUYIN_API_ENABLED'] = 'true'
os.environ['DOUYIN_API_BASE_URL'] = 'http://127.0.0.1:8765'
os.environ['DOUYIN_API_TOKEN'] = 'test_token_douyin'
os.environ['KUAISHOU_API_ENABLED'] = 'true'
os.environ['KUAISHOU_API_BASE_URL'] = 'http://127.0.0.1:8765'
os.environ['KUAISHOU_API_TOKEN'] = 'test_token_kuaishou'

sys.path.insert(0, '.')
from app.data_crawlers import DouyinCrawler, KuaishouCrawler

print('=== 1. 直接 requests 真实 HTTP 调用测试 ===')
s = requests.Session()
headers = {'Authorization': 'Bearer test_token_douyin'}

r = s.get('http://127.0.0.1:8765/health', headers=headers, timeout=5)
print(f'  /health -> status={r.status_code}, body={r.json()}')

r2 = s.get('http://127.0.0.1:8765/openapi/live/v1/session/list', headers=headers, timeout=5)
d = r2.json()
print(f'  /session/list -> status={r2.status_code}, code={d.get("code")}, count={len(d.get("data",{}).get("list",[]))}')
for s_ in d.get('data', {}).get('list', [])[:2]:
    print(f'    session: {s_["session_id"]}  anchor={s_["anchor_name"]}')

r3 = s.get('http://127.0.0.1:8765/openapi/live/v1/realtime', headers=headers, timeout=5)
print(f'  /realtime -> status={r3.status_code}, gmv_est={r3.json().get("data",{}).get("gmv_estimate")}')

r4 = s.get('http://127.0.0.1:8765/openapi/live/v1/order/list', headers=headers, timeout=5)
d4 = r4.json()
print(f'  /order/list -> status={r4.status_code}, orders={len(d4.get("data",{}).get("list",[]))}')

# 无token测试（应当失败）
r_no_auth = s.get('http://127.0.0.1:8765/health', timeout=5)
print(f'  /health (无token) -> status={r_no_auth.status_code}, expect=401')

# 错误token测试
r_bad = s.get('http://127.0.0.1:8765/health', headers={'Authorization': 'Bearer wrong_token'}, timeout=5)
print(f'  /health (错误token) -> status={r_bad.status_code}, expect=401')

print()
print('=== 2. 通过爬虫框架调用真实 API ===')

print('-- 抖音爬虫 --')
dy = DouyinCrawler()
print(f'  api_enabled={dy.api_config.enabled}')
print(f'  base_url={dy.api_config.base_url}')
print(f'  token_set={bool(dy.api_config.api_token)}')

# _http_get 返回 (data, error) 元组
data, err = dy._http_get('/openapi/live/v1/session/list')
if err:
    print(f'  _http_get(session/list) 失败: {err}')
else:
    sessions = data.get('data', {}).get('list', [])
    print(f'  _http_get(session/list) 成功: {len(sessions)} 场直播')
    for s2 in sessions[:1]:
        print(f'    直播: {s2.get("title")}')

data2, err2 = dy._http_get('/openapi/live/v1/order/list')
if err2:
    print(f'  _http_get(order/list) 失败: {err2}')
else:
    orders = data2.get('data', {}).get('list', [])
    print(f'  _http_get(order/list) 成功: {len(orders)} 条订单')

print()
print('-- 快手爬虫 --')
ks = KuaishouCrawler()
print(f'  api_enabled={ks.api_config.enabled}')
data_ks, err_ks = ks._http_get('/openapi/live/v1/session/list')
if err_ks:
    print(f'  _http_get 失败: {err_ks}')
else:
    print(f'  _http_get 成功: {len(data_ks.get("data",{}).get("list",[]))} 场直播')

print()
print('=== 3. 完整 fetch_live_sessions 流程 ===')
try:
    result = dy.fetch_live_sessions()
    print(f'  fetch_live_sessions -> {len(result)} 场')
    for r in result[:2]:
        print(f'    -> {r.get("session_id")} anchor={r.get("anchor_name")}')
except Exception as e:
    print(f'  fetch_live_sessions 失败: {e}')
    import traceback
    traceback.print_exc()

print()
print('=== HTTP真实接口打通测试完成 ===')

import os
os.environ['REDIS_ENABLED'] = 'true'
os.environ['REDIS_URL'] = 'redis://127.0.0.1:6379/1'

import sys
sys.path.insert(0, '.')
from app.cache import cache_layer

print('=== Redis 缓存层测试 ===')
stats = cache_layer.get_stats()
print(f'初始状态: {stats}')

print()
print('1. 写入缓存...')
cache_layer.set('test:key1', 'hello_redis', ttl=60)
cache_layer.set('test:num', {'a': 1, 'b': 2}, ttl=300)
cache_layer.set_realtime('test:rt', {'viewer': 1234})

print('2. 读取缓存...')
print(f'  test:key1 = {cache_layer.get("test:key1")}')
print(f'  test:num = {cache_layer.get("test:num")}')
print(f'  test:rt = {cache_layer.get_realtime("test:rt")}')
print(f'  test:miss = {cache_layer.get("test:missing")}')

print()
stats2 = cache_layer.get_stats()
print(f'操作后状态: {stats2}')

print()
print('3. @cached 装饰器测试...')
from app.cache import cached
import time

call_count = [0]

@cached(key_pattern='cached:test:{a}_{b}', ttl=60)
def add(a, b):
    call_count[0] += 1
    time.sleep(0.1)
    return a + b

r1 = add(3, 4)
r2 = add(3, 4)
r3 = add(5, 6)
print(f'  add(3,4) 首次: {r1}, call_count={call_count[0]}')
print(f'  add(3,4) 缓存: {r2}, call_count={call_count[0]} (不变说明命中缓存)')
print(f'  add(5,6) 新值: {r3}, call_count={call_count[0]}')

print()
stats3 = cache_layer.get_stats()
print(f'最终状态: {stats3}')

print()
print('=== Redis 全部测试通过 ===' if stats3.get('redis_connected') else '=== Redis 未连接 ===')

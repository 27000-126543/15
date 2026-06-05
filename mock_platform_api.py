#!/usr/bin/env python3
"""模拟平台开放接口的本地Mock服务器，用于测试requests真实HTTP调用"""
import json
import random
import sys
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

random.seed(42)

PLATFORMS = ["douyin", "kuaishou", "taobao", "wechat", "bilibili"]


class MockPlatformAPIHandler(BaseHTTPRequestHandler):
    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        token = auth.split("Bearer ", 1)[1].strip()
        return token in {"test_token_douyin", "test_token_kuaishou", "test_token_taobao",
                         "test_token_wechat", "test_token_bilibili", "test_token"}

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_platform(self) -> str:
        # 从Host或token或路径中推断平台
        auth = self.headers.get("Authorization", "")
        token = auth.split("Bearer ", 1)[1].strip() if auth.startswith("Bearer ") else ""
        for plat in PLATFORMS:
            if plat in token or plat in self.path:
                return plat
        return "douyin"

    def do_GET(self):
        print(f"[MockAPI] GET {self.path}  auth={self.headers.get('Authorization', '')[:50]}...",
              file=sys.stderr, flush=True)
        if not self._check_auth():
            self._send_json(401, {"error": "unauthorized", "message": "Invalid or missing Bearer token"})
            return

        plat = self._get_platform()
        path = self.path.split("?", 1)[0]

        # 直播场次列表
        if "session" in path.lower() and "list" in path.lower():
            sessions = []
            for i in range(random.randint(2, 5)):
                sid = f"{plat}_{datetime.now().strftime('%Y%m%d')}_{random.randint(100000,999999)}"
                sessions.append({
                    "session_id": sid,
                    "anchor_id": f"{plat}_anchor_{random.randint(1,50)}",
                    "anchor_name": f"测试主播_{plat}_{i+1}",
                    "start_time": (datetime.now() - timedelta(hours=random.randint(0,6))).isoformat(),
                    "status": "live",
                    "title": f"{plat.upper()} 直播测试标题 #{i+1}",
                    "category": random.choice(["美妆", "服饰", "食品", "数码", "生活"]),
                })
            self._send_json(200, {"code": 0, "msg": "success", "data": {"list": sessions, "total": len(sessions)}})
            return

        # 实时数据
        if "realtime" in path.lower() or "live" in path.lower() and "data" in path.lower():
            self._send_json(200, {
                "code": 0, "msg": "success",
                "data": {
                    "viewer_count": random.randint(500, 50000),
                    "new_viewers": random.randint(50, 5000),
                    "online_count": random.randint(100, 10000),
                    "like_count": random.randint(1000, 100000),
                    "comment_count": random.randint(50, 5000),
                    "share_count": random.randint(10, 1000),
                    "gmv_estimate": round(random.uniform(1000, 500000), 2),
                    "timestamp": datetime.now().isoformat(),
                }
            })
            return

        # 订单列表
        if "order" in path.lower() and "list" in path.lower():
            orders = []
            for i in range(random.randint(3, 15)):
                orders.append({
                    "order_id": f"O{plat}{datetime.now().strftime('%Y%m%d%H%M')}{random.randint(1000,9999)}",
                    "session_id": f"{plat}_{datetime.now().strftime('%Y%m%d')}_mock",
                    "sku": f"SKU{plat}{random.randint(100,999)}",
                    "product_name": f"测试商品_{plat}_{i+1}",
                    "quantity": random.randint(1, 5),
                    "unit_price": round(random.uniform(29, 999), 2),
                    "paid_amount": round(random.uniform(29, 4999), 2),
                    "buyer_nick": f"买家***{random.randint(100,999)}",
                    "order_time": (datetime.now() - timedelta(minutes=random.randint(1,180))).isoformat(),
                    "status": "paid",
                })
            self._send_json(200, {"code": 0, "msg": "success", "data": {"list": orders, "total": len(orders)}})
            return

        # 商品列表
        if "product" in path.lower() and "list" in path.lower():
            products = []
            for i in range(random.randint(5, 12)):
                products.append({
                    "sku": f"SKU{plat}{100+i}",
                    "name": f"测试商品_{plat}_{i+1}",
                    "category": random.choice(["美妆", "服饰", "食品", "数码", "生活"]),
                    "price": round(random.uniform(29, 999), 2),
                    "stock": random.randint(100, 10000),
                })
            self._send_json(200, {"code": 0, "msg": "success", "data": {"list": products, "total": len(products)}})
            return

        # 健康检查
        if "health" in path.lower():
            self._send_json(200, {"code": 0, "msg": "mock platform api running", "platform": plat})
            return

        self._send_json(404, {"code": 404, "msg": f"not found: {path}"})

    def log_message(self, format, *args):
        print(f"[MockAPI] {format % args}", file=sys.stderr, flush=True)


def main(port=8765):
    server = ThreadingHTTPServer(("127.0.0.1", port), MockPlatformAPIHandler)
    print(f"[MockAPI] 本地平台Mock API启动于 http://127.0.0.1:{port}", file=sys.stderr, flush=True)
    print(f"[MockAPI] 测试token: Bearer test_token_douyin / test_token_kuaishou / ...",
          file=sys.stderr, flush=True)
    print(f"[MockAPI] 可用接口: /health, /openapi/live/v1/session/list, /openapi/live/v1/realtime",
          file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[MockAPI] 服务器停止", file=sys.stderr, flush=True)


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    main(p)

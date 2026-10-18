"""本地演示用假接口：按时间轴改变票种状态，用来观察监控器的显示与去抖效果。

用法：
    python test/mock_sale_server.py              # 监听 127.0.0.1:5001
    python aili_ticket_monitor.py --api-url ^
        "http://127.0.0.1:5001/api/ticket/project/getV2?version=134&id=900001" ^
        --interval 2 --log --log-file demo.log

时间轴（从第一次请求开始计时，单位秒）：
    0–12   基线：6 个票种，1 个已售罄、1 个预售中，其余未开售
    12–22  A/B/C 三个票种同时开售（3 条「状态变化」）
    22–36  D 每次请求在「预售中 / 已售罄」之间来回跳（秒级抖动，应当被过滤）
    36–46  D 稳定在「预售中」（连续 2 次后确认 1 条「状态变化」）
    46–56  E 从「预售中」变成「已售罄」（1 条）
    56–66  新增 G（1 条「新增票种」）
    66–76  移除 F（1 条「移除票种」）
    80–87  连续返回 HTTP 500（连发才不会被自动重试吞掉，能观察到错误计数与退避）
    88     返回一次 HTTP 429（观察限流提示）
    76–96  状态稳定
    96     从头再来一轮（时间轴循环，方便随时观察）

所有控制台输出只用 ASCII，避免 GBK 控制台崩溃；JSON 里的中文照常以 UTF-8 传输。
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"
PORT = 5001
CYCLE = 96  # 时间轴一轮的长度（秒）

SCREEN_A = "2026-11-14 周六"
SCREEN_B = "2026-11-15 周日"

# (内部代号, 场次, 票种名)
TICKETS = [
    ("A", SCREEN_A, "VIP票（含礼包）"),
    ("B", SCREEN_A, "单日票"),
    ("C", SCREEN_A, "游园票"),
    ("D", SCREEN_B, "VIP票（含礼包）"),
    ("E", SCREEN_B, "单日票"),
    ("F", SCREEN_B, "游园票"),
]
EXTRA = ("G", SCREEN_B, "两日联票")

STARTED = time.monotonic()
REQUESTS = 0
LAST_429_CYCLE = -1


def elapsed() -> float:
    return time.monotonic() - STARTED


def status_of(code: str, seconds: float, request_no: int) -> str:
    """按时间轴算出某个票种此刻的状态。"""
    if code == "A":
        return "预售中" if seconds >= 12 else "未开售"
    if code == "B":
        return "预售中" if seconds >= 12 else "未开售"
    if code == "C":
        return "预售中" if seconds >= 12 else "已售罄"
    if code == "D":
        if 22 <= seconds < 36:  # 抖动段：每次请求都反转
            return "预售中" if request_no % 2 else "已售罄"
        if seconds >= 36:
            return "预售中"
        return "未开售"
    if code == "E":
        return "已售罄" if seconds >= 46 else "预售中"
    if code == "F":
        return "未开售"
    if code == "G":
        return "暂时售罄"
    return "未知"


def visible_tickets(seconds: float) -> list[tuple[str, str, str]]:
    rows = list(TICKETS)
    if seconds >= 56:
        rows.append(EXTRA)
    if seconds >= 66:
        rows = [row for row in rows if row[0] != "F"]
    return rows


def build_payload(seconds: float, request_no: int) -> dict:
    screens: dict[str, list[dict]] = {SCREEN_A: [], SCREEN_B: []}
    for code, screen, desc in visible_tickets(seconds):
        status = status_of(code, seconds, request_no)
        screens[screen].append(
            {
                "id": abs(hash(code)) % 10000,
                "desc": desc,
                "price": 128,
                "sale_flag": {
                    "name": status,
                    "display_name": status,
                    "color": "grey",
                },
            }
        )

    return {
        "code": 0,
        "success": True,
        "message": "",
        "data": {
            "id": 900001,
            "name": "模拟场次 · BW 余票演示",
            "screen_list": [
                {"id": 1, "name": SCREEN_A, "ticket_list": screens[SCREEN_A]},
                {"id": 2, "name": SCREEN_B, "ticket_list": screens[SCREEN_B]},
            ],
            "ticket_list": [],
        },
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # 静音默认访问日志
        pass

    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        global REQUESTS, LAST_429_CYCLE
        REQUESTS += 1
        total = elapsed()
        cycle = int(total // CYCLE)
        seconds = total % CYCLE  # 每 CYCLE 秒重演一次，方便反复观察

        if "getV2" not in self.path:
            self._send(404, b'{"code":404,"message":"not found"}')
            return

        # 500 要连发几秒，否则会被 urllib3 的自动重试（total=2）吞掉，监控端根本看不到错误
        if 80 <= seconds < 87:
            print(f"[mock] #{REQUESTS} t={seconds:5.1f}s -> HTTP 500", flush=True)
            self._send(500, b'{"code":500,"message":"server error"}')
            return

        if seconds >= 88 and LAST_429_CYCLE != cycle:
            LAST_429_CYCLE = cycle
            print(f"[mock] #{REQUESTS} t={seconds:5.1f}s -> HTTP 429 (once)", flush=True)
            self._send(429, b'{"code":429,"message":"too many requests"}')
            return

        payload = build_payload(seconds, REQUESTS)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        count = sum(len(s["ticket_list"]) for s in payload["data"]["screen_list"])
        states = "/".join(
            f"{t['desc'][:2]}:{t['sale_flag']['display_name']}"
            for s in payload["data"]["screen_list"]
            for t in s["ticket_list"]
        )
        print(f"[mock] #{REQUESTS} t={seconds:5.1f}s tickets={count} {states}", flush=True)
        self._send(200, body)


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"[mock] listening on http://{HOST}:{PORT}", flush=True)
    print(
        "[mock] url: http://127.0.0.1:5001/api/ticket/project/getV2?version=134&id=900001",
        flush=True,
    )
    print(
        "[mock] timeline: 0-12 base | 12 open A/B/C | 22-36 flap D | 36 D stable"
        " | 46 E sold out | 56 add G | 66 remove F | 80 500 | 88 429"
        f"  (loops every {CYCLE}s)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[mock] bye", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

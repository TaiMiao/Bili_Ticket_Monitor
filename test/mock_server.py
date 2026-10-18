"""
B站票务 API Mock 服务器 - 包含 429 流量限制测试
支持：
- 正常票务状态变化（未开售 → 预售中 → 部分售罄）
- HTTP 500 错误（第3次）
- 请求超时（第4次，延迟60秒）
- 429 流量限制（第5次）
- 412 风控（最后一次，并自动重置）
- URL 参数控制（mode=429 可立即触发429）
"""

from flask import Flask, jsonify, request
import time
import copy
import threading

app = Flask(__name__)

# ==================== 基础数据 ====================
BASE_DATA = {
    "success": True,
    "data": {
        "name": "上海·BILIBILI MACRO LINK-PLAY!  2026",
        "screen_list": [
            {
                "id": 1009286,
                "name": "2026-07-11 周六",
                "ticket_list": [
                    {"desc": "大会员提前抢-D级", "sale_flag": {"display_name": "未开售"}},
                    {"desc": "大会员提前抢-C级", "sale_flag": {"display_name": "未开售"}},
                    {"desc": "大会员提前抢-B级（看台）", "sale_flag": {"display_name": "未开售"}},
                    {"desc": "大会员提前抢-B级（内场）", "sale_flag": {"display_name": "未开售"}},
                    {"desc": "大会员提前抢-A级", "sale_flag": {"display_name": "未开售"}},
                    {"desc": "大会员提前抢-S级", "sale_flag": {"display_name": "未开售"}},
                ]
            },
            {
                "id": 1009287,
                "name": "2026-07-12 周日",
                "ticket_list": [
                    {"desc": "大会员提前抢-D级", "sale_flag": {"display_name": "未开售"}},
                    {"desc": "大会员提前抢-C级", "sale_flag": {"display_name": "未开售"}},
                    {"desc": "大会员提前抢-B级（内场）", "sale_flag": {"display_name": "未开售"}},
                    {"desc": "大会员提前抢-B级（看台）", "sale_flag": {"display_name": "未开售"}},
                    {"desc": "大会员提前抢-A级", "sale_flag": {"display_name": "未开售"}},
                    {"desc": "大会员提前抢-S级", "sale_flag": {"display_name": "未开售"}},
                ]
            }
        ],
        "id": 1001701,
        "status": 1,
        "sale_flag": "未开售",
        "current_time": int(time.time())
    },
    "code": 0,
    "message": "success"
}

# 全局可变状态
request_counter = 0
mock_data = copy.deepcopy(BASE_DATA)
lock = threading.Lock()

def reset_mock_state():
    """重置计数器与数据到初始状态"""
    global request_counter, mock_data
    with lock:
        request_counter = 0
        mock_data = copy.deepcopy(BASE_DATA)
        print("[Mock] 🔄 状态已重置")

def apply_state_changes(counter):
    """根据请求次数修改数据（仅在正常响应时调用）"""
    # 第2次及之后：全变预售中
    if counter >= 2:
        for screen in mock_data["data"]["screen_list"]:
            for ticket in screen["ticket_list"]:
                ticket["sale_flag"]["display_name"] = "预售中"

    # 第3次：周六场增加新票种 VVIP包厢
    if counter == 3:
        new_ticket = {
            "desc": "大会员提前抢-VVIP包厢",
            "sale_flag": {"display_name": "预售中"}
        }
        mock_data["data"]["screen_list"][0]["ticket_list"].append(new_ticket)
        print(f"[Mock] 第{counter}次 → ➕ 新增 VVIP包厢")

    # 第6次：部分售罄（周六D级、周日S级）
    if counter == 6:
        saturday_d = mock_data["data"]["screen_list"][0]["ticket_list"][0]
        saturday_d["sale_flag"]["display_name"] = "已售罄"
        sunday_s = mock_data["data"]["screen_list"][1]["ticket_list"][5]
        sunday_s["sale_flag"]["display_name"] = "已售罄"
        print(f"[Mock] 第{counter}次 → ✅ 部分售罄")

# ==================== Flask 路由 ====================
@app.route('/api/ticket/project/getV2', methods=['GET'])
def mock_api():
    global request_counter
    with lock:
        request_counter += 1
        current_count = request_counter

    print(f"\n[Mock] 📨 第 {current_count} 次请求")

    # ----- 通过 URL 参数直接触发特定行为（优先级最高）-----
    mode = request.args.get('mode', '')
    if mode == '429':
        print("[Mock] 🚦 直接触发 429 流量限制")
        return jsonify({"error": "Too Many Requests"}), 429
    elif mode == '500':
        print("[Mock] 🔥 触发 500")
        return jsonify({"error": "Internal Error"}), 500
    elif mode == '412':
        print("[Mock] 🚫 触发 412 风控")
        return jsonify({"error": "Risk Control"}), 412
    elif mode == 'timeout':
        print("[Mock] ⏰ 模拟超时 60 秒")
        time.sleep(60)

    # ----- 计数器触发的错误 -----
    # 第3次 -> 500
    if current_count == 3:
        print("[Mock] 🔥 返回 500")
        return jsonify({"error": "Internal Error"}), 500

    # 第4次 -> 超时（延迟60秒）
    if current_count == 4:
        print("[Mock] ⏰ 模拟超时 60 秒")
        time.sleep(60)

    # 第5次 -> 429 流量限制（脚本收到后应显示“流量限制 (429)”并继续）
    if current_count == 5:
        print("[Mock] 🚦 返回 429 Too Many Requests")
        return jsonify({"error": "Too Many Requests"}), 429

    # 第7次 -> 412 风控（最后一次，自动重置）
    if current_count == 7:
        print("[Mock] 🚫 返回 412 风控，并重置状态")
        reset_mock_state()
        return jsonify({"error": "Risk Control"}), 412

    # ----- 正常响应：应用状态变化 -----
    apply_state_changes(current_count)
    mock_data["data"]["current_time"] = int(time.time())
    return jsonify(mock_data)

# ==================== 调试接口 ====================
@app.route('/mock/status', methods=['GET'])
def get_status():
    with lock:
        summary = []
        for screen in mock_data["data"]["screen_list"]:
            tickets_summary = [f"{t['desc']}:{t['sale_flag']['display_name']}" for t in screen['ticket_list']]
            summary.append(f"{screen['name']} -> {tickets_summary}")
        return jsonify({
            "request_counter": request_counter,
            "tickets_summary": summary
        })

@app.route('/mock/reset', methods=['POST'])
def reset():
    reset_mock_state()
    return jsonify({"message": "Reset OK"})

if __name__ == '__main__':
    print("=" * 70)
    print("B站票务 API Mock 服务器（含 429 测试）")
    print("监听地址: http://127.0.0.1:5000")
    print("\n默认计数器行为时间线：")
    print("  1. 未开售")
    print("  2. 全部变预售中")
    print("  3. 500 错误")
    print("  4. 超时（延迟60秒）")
    print("  5. 429 流量限制")
    print("  6. 部分售罄（周六D级、周日S级）")
    print("  7. 412 风控 + 自动重置")
    print("\nURL 参数控制（立即触发，无视计数器）：")
    print("  ?mode=429   - 立即返回 429")
    print("  ?mode=500   - 立即返回 500")
    print("  ?mode=412   - 立即返回 412")
    print("  ?mode=timeout - 延迟60秒")
    print("\n调试接口：")
    print("  GET  /mock/status   - 查看当前状态")
    print("  POST /mock/reset    - 手动重置")
    print("=" * 70)
    app.run(host='127.0.0.1', port=5000, debug=False)
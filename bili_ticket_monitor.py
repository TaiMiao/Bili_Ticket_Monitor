"""Bili_Ticket_Monitor by TaiMiao & ChatGPT"""

import time
import random
import threading
from datetime import datetime
import requests
from colorama import Fore, Style, init
from tabulate import tabulate
from wcwidth import wcswidth

# 可以修改的配置
TICKET_ID = "请替换这里"  # 请替换为实际票务ID
REFRESH_INTERVAL = 2  # 票务信息刷新间隔（秒），设置太低可能会被风控
TIMEOUT = 50  # 请求超时时间，根据网络状况设置
MAX_RETRIES = 3  # 网络连接失败后最大重试次数

# 别动！！
API_URL = f"https://show.bilibili.com/api/ticket/project/getV2?version=134&id={TICKET_ID}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
    )
}


def clear_screen():
    """使用ANSI转义序列清除屏幕"""
    print("\033c", end="")

def fetch_data(max_retries=MAX_RETRIES, pause_event=None):
    """获取票务状态"""
    for attempt in range(max_retries):
        try:
            response = requests.get(API_URL, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json().get('data', {})
            name = data.get('name', '')  # 获取名称
            tickets = [
                [
                    ticket.get('screen_name', '') + " " + ticket.get('desc', ''),
                    ticket.get('sale_flag', {}).get('display_name', '')
                ]
                for screen in data.get('screen_list', [])
                for ticket in screen.get('ticket_list', [])
            ]

            if not tickets:
                print(Fore.RED + "\n数据为空，请检查票务ID")
                return None, None

            if attempt > 0:  # 当重试成功时
                print(Fore.GREEN + "\n重连成功")
                show_table(name, tickets, pause_event=pause_event)  # 重新打印表格

            return name, tickets

        except requests.RequestException as e:
            handle_request_exception(e, attempt, max_retries, pause_event)

    return None, None

def handle_request_exception(e, attempt, max_retries, pause_event=None):
    """处理请求异常"""
    if pause_event is not None:
        pause_event.set()  # 时间线程暂停

    if e.response is not None and e.response.status_code == 412:
        print(Fore.RED + "\nIP可能被业务风控，请暂停操作，否则会引起更大问题")
        raise SystemExit  # 直接退出程序

    print(Fore.RED + f"\n请求错误，请检查网络: {e}")

    # 指数退避和抖动策略
    if attempt < max_retries - 1:
        backoff = (2 ** attempt) + random.uniform(0, 1)  # 随机抖动
        print(Fore.YELLOW + f"重试中... ({attempt + 1}/{max_retries})，等待{backoff:.2f}秒")
        time.sleep(backoff)
    else:
        print(Fore.RED + "\n多次尝试获取票务状态失败，程序即将退出")

    if pause_event is not None:
        pause_event.clear()  # 恢复时间显示

def show_table(name, table, first_time=False, pause_event=None):
    """打印票务状态表，根据状态进行颜色编码"""
    if pause_event is not None:
        pause_event.set()  # 时间线程暂停

    max_desc = max(calc_width(row[0]) for row in table)
    max_status = max(len(row[1]) for row in table)

    if not first_time:
        print()  # 输出空行

    print(f"{Style.BRIGHT}{name}")
    print(f"{Fore.CYAN}{'票种'.ljust(max_desc)}{'状态'.rjust(max_status)}")
    print('-' * (max_desc + max_status + 8))

    all_data = [[row[0], colorize(row[1])] for row in table]
    print(tabulate(all_data, tablefmt='plain'))

    if pause_event is not None:
        pause_event.clear()  # 恢复时间显示

def calc_width(text):
    """计算文本的显示宽度"""
    return wcswidth(text)

def colorize(status):
    """根据状态添加颜色"""
    color_map = {
        "已售罄": Fore.RED,
        "已停售": Fore.RED,
        "不可售": Fore.RED,
        "未开售": Fore.RED,
        "暂时售罄": Fore.YELLOW,
        "预售中": Fore.GREEN,
    }
    return color_map.get(status, Fore.WHITE) + status + Style.RESET_ALL

def has_changed(old, new):
    """检查状态是否发生变化"""
    return old != new

def show_time(stop_event, pause_event):
    """显示当前时间"""
    last_printed_time = None  # 上次打印的时间
    while not stop_event.is_set():  # 检测停止事件
        if not pause_event.is_set():  # 检查是否需要暂停
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if current_time != last_printed_time:
                print(f"{Fore.GREEN}当前时间: {current_time}", end='\r')
                last_printed_time = current_time

def monitor(stop_event, pause_event):
    """监控状态并刷新显示"""
    last_table = None
    first_time = True  # 是否第一次打印表格

    # 初次获取票务状态
    name, new_table = fetch_data(pause_event=pause_event)
    if new_table is None:
        return

    show_table(name, new_table, first_time, pause_event)
    last_table = new_table

    while not stop_event.is_set():  # 检测停止事件
        time.sleep(REFRESH_INTERVAL)
        name, new_table = fetch_data(pause_event=pause_event)

        if new_table is None:
            break

        # 如果状态发生变化，更新显示
        if has_changed(last_table, new_table):
            show_table(name, new_table, not last_table, pause_event)
            last_table = new_table

def main():
    """主程序"""
    # 初始化颜色输出
    init(autoreset=True)
    stop_event = threading.Event()  # 创建停止事件
    pause_event = threading.Event()  # 创建暂停事件

    # 创建并启动线程
    time_thread = threading.Thread(target=show_time, args=(stop_event, pause_event), daemon=True)
    ticket_thread = threading.Thread(target=monitor, args=(stop_event, pause_event), daemon=True)
    ticket_thread.start()
    time.sleep(0.5)  # 等待线程启动
    time_thread.start()

    # 等待线程完成
    ticket_thread.join()
    stop_event.set()  # 设置停止事件，结束时间显示线程

if __name__ == "__main__":
    main()
    input("\n按回车键退出...")

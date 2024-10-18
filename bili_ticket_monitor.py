"""Bili_Ticket_Monitor"""

import time
from datetime import datetime
import os
import requests
from colorama import Fore, Style, init
from tabulate import tabulate
from wcwidth import wcswidth

# 可修改的东西
TICKET_ID = "请替换这里"  # 请替换为实际票务ID
TICKET_REFRESH_INTERVAL = 2  # 票务信息刷新间隔，1秒以下可能会被风控
TIMEOUT = 10  # 请求超时时间，根据网络状况设置
MAX_RETRIES = 3  # 网络连接失败后最大重试次数

# 不要动下面的东西！！！
BASE_URL = f"https://show.bilibili.com/api/ticket/project/getV2?version=134&id={TICKET_ID}"
SLEEP_INTERVAL = 0.01  # 时间显示刷新间隔
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36"
    )
}

# 初始化颜色输出
init(autoreset=True)

def clear_screen():
    """清除屏幕，根据操作系统类型进行判断。"""
    if os.name == 'nt':  # Windows系统
        os.system('cls')
    else:  # Mac和Linux系统
        os.system('clear')

def fetch_ticket_status(max_retries=MAX_RETRIES):
    """从Bilibili API获取票务状态，若失败则重试。"""
    for attempt in range(max_retries):
        try:
            response = requests.get(BASE_URL, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json().get('data', {})
            name = data.get('name', '')
            tickets = [
                [
                    ticket.get('screen_name', '') + ticket.get('desc', '').replace("普通票", "普通票"),
                    ticket.get('sale_flag', {}).get('display_name', '')
                ]
                for screen in data.get('screen_list', [])
                for ticket in screen.get('ticket_list', [])
            ]

            if not tickets:
                print(Fore.RED + "数据为空，请检查票务ID")
                return None, None

            return name, tickets

        except requests.RequestException as e:
            if e.response is not None and e.response.status_code == 412:
                print("")
                print(Fore.RED + "IP可能被业务风控，请暂停操作，否则会引起更大问题。")
                return None, None
            print(Fore.RED + f"请求错误，请检查网络: {e}")
            if attempt < max_retries - 1:
                print(Fore.YELLOW + f"重试中... ({attempt + 1}/{max_retries})")
                time.sleep(1)  # 等待1秒后重试

    print(Fore.RED + "多次尝试获取票务状态失败，程序即将退出。")
    return None, None

def print_ticket_table(name, table):
    """打印票务状态表，并根据状态进行颜色编码。"""
    max_desc_len = max(calculate_display_width(row[0]) for row in table)
    max_status_len = max(len(row[1]) for row in table)

    print("")
    print(f"{Style.BRIGHT}{name}")
    print(f"{Fore.CYAN}{'票种'.ljust(max_desc_len)}{'状态'.rjust(max_status_len)}")
    print('-' * (max_desc_len + max_status_len + 8))

    all_data = [[row[0], color_status(row[1])] for row in table]
    print(tabulate(all_data, tablefmt='plain'))

def calculate_display_width(text):
    """计算文本的显示宽度。"""
    return wcswidth(text)

def color_status(status):
    """根据票务状态的值为其添加颜色。"""
    color_map = {
        "已售罄": Fore.RED,
        "已停售": Fore.RED,
        "不可售": Fore.RED,
        "未开售": Fore.RED,
        "暂时售罄": Fore.YELLOW,
        "预售中": Fore.GREEN,
    }
    return color_map.get(status, Fore.WHITE) + status + Style.RESET_ALL

def has_table_changed(old_table, new_table):
    """检查票务状态表是否发生变化。"""
    return old_table != new_table

def display_time():
    """在不清除上一行的情况下显示当前时间。"""
    print(f"{Fore.GREEN}当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", end='\r', flush=True)

def main():
    """监控票务状态并刷新显示。"""
    last_table = None
    last_request_time = 0  # 上次请求的时间

    # 初次获取票务状态
    name, new_table = fetch_ticket_status()
    if new_table is None:
        return

    print_ticket_table(name, new_table)
    last_table = new_table
    last_request_time = time.time()  # 记录初次请求的时间

    while True:
        try:
            current_time = time.time()

            # 检查是否达到下次网络请求的间隔
            if current_time - last_request_time >= TICKET_REFRESH_INTERVAL:
                name, new_table = fetch_ticket_status()
                last_request_time = current_time  # 更新上次请求的时间

                if new_table is None:
                    break

                # 如果票务状态发生变化，更新显示
                if has_table_changed(last_table, new_table):
                    clear_screen()  # 清屏后重新打印表格
                    print_ticket_table(name, new_table)
                    last_table = new_table

            # 刷新时间显示
            display_time()
            time.sleep(SLEEP_INTERVAL)

        except ImportError as e:
            print(Fore.RED + f"程序发生错误: {e}")
            break

if __name__ == "__main__":
    main()
    input("按回车键退出...")

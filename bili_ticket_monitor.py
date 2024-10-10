"""
Bili Ticket Monitor

This script monitors the status of tickets for a specific event on Bilibili.
"""

import time
from datetime import datetime
import requests
from colorama import Fore, Style, init
from tabulate import tabulate
from wcwidth import wcswidth

# 可以修改的东西
TICKET_ID = "请替换这里"  # 请替换为实际票务ID
TICKET_REFRESH_INTERVAL = 2  # 票务信息刷新间隔，1秒以下可能会被风控
TIMEOUT = 100  # 请求超时时间，根据网络状况设置

# 不要动下面的东西！！！
BASE_URL = f"https://show.bilibili.com/api/ticket/project/getV2?version=134&id={TICKET_ID}"
SLEEP_INTERVAL = 0.5  # 时间显示刷新间隔
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36"
    )
}

# 初始化颜色输出
init(autoreset=True)

def clear_screen_line():
    """Clear the current line in the terminal."""
    print("\033[F\033[K", end="")  # 清除终端当前行的内容

def fetch_ticket_status(url, headers):
    """Fetch the ticket status from the Bilibili API.

    Args:
        url (str): The API endpoint URL.
        headers (dict): HTTP headers for the request.

    Returns:
        tuple: Event name and the table of ticket information, or (None, None) on error.
    """
    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json().get('data', {})
        tickets = data.get('screen_list', [])
        name = data.get('name', '')

        if not tickets:
            print(Fore.RED + "数据为空，请检查票务ID")
            return None, None

        table = [
            [
                ticket.get('screen_name', '') + ticket.get('desc', '').replace("普通票", "普通票"),
                ticket.get('sale_flag', {}).get('display_name', '')
            ]
            for screen in tickets for ticket in screen.get('ticket_list', [])
        ]

        return name, table

    except requests.exceptions.RequestException as e:
        if e.response or e.response.status_code == 412:
            print(Fore.RED + "IP被风控，请等待一段时间后继续，否则将会引发更大的问题")
        else:
            print(Fore.RED + f"请求错误(请检查网络连接): {e}")
        return None, None

def print_ticket_table(name, table):
    """Print the ticket table with color coding.

    Args:
        name (str): Event name.
        table (list): List of tickets with their descriptions and status.
    """
    if not table:
        return

    max_desc_len = max(len(row[0]) for row in table)
    max_status_len = max(len(row[1]) for row in table)

    # 计算真实显示字符长度
    max_display_desc_len = calculate_display_width(
        max(table, key=lambda x: len(x[0]))[0]
        .replace('）', ')').replace('（', '(').replace('：', ':')
    )

    print(f"{Style.BRIGHT}{name}")
    print(f"{Fore.CYAN}{'票种'.ljust(max_display_desc_len)}{'状态'.rjust(max_status_len)}")
    print('-' * (max_desc_len + max_status_len + 16))

    # 用tabulate库打印
    all_data = [
        [row[0].replace('）', ')').replace('（', '(').replace('：', ':'), color_status(row[1])]
        for row in table
    ]
    print(tabulate(all_data, tablefmt='plain'))

def calculate_display_width(text):
    """Calculate the display width of the text.

    Args:
        text (str): The text to calculate.

    Returns:
        int: The total display width of the text.
    """
    return sum(wcswidth(char) for char in text)

def color_status(status):
    """Color the ticket status based on its current value.

    Args:
        status (str): The status text.

    Returns:
        str: The colored status string.
    """
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
    """Check if the ticket table has changed.

    Args:
        old_table (list): The previous ticket table.
        new_table (list): The new ticket table.

    Returns:
        bool: True if the table has changed, False otherwise.
    """
    return old_table != new_table

def display_time():
    """Display the current time."""
    print(f"{Fore.GREEN}当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def main():
    """Main function to monitor ticket status and refresh the display."""
    last_table = None
    name, new_table = fetch_ticket_status(BASE_URL, HEADERS)

    if new_table is None:
        return  # 如果没有数据则退出

    print_ticket_table(name, new_table)
    last_table = new_table

    while True:
        try:
            if time.time() % TICKET_REFRESH_INTERVAL < SLEEP_INTERVAL:
                name, new_table = fetch_ticket_status(BASE_URL, HEADERS)
                if new_table is None:
                    break  # 如果没有新的数据则退出

                if has_table_changed(last_table, new_table):
                    print_ticket_table(name, new_table)
                    last_table = new_table

            clear_screen_line()
            display_time()
            time.sleep(SLEEP_INTERVAL)

        except requests.exceptions.RequestException as e:
            if e.response or e.response.status_code == 412:
                print(Fore.RED + "IP被风控，请等待一段时间后继续，否则将会引发更大的问题")
            else:
                print(Fore.RED + f"请求错误(请检查网络连接): {e}")
            break  # 出现错误时停止循环

if __name__ == "__main__":
    main()
    input("按回车键退出...")

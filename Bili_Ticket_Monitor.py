import requests
import time
import json
from datetime import datetime
from colorama import Fore, Style, init
import os

def clear_screen():
    if os.name == 'nt':  # Windows系统
        os.system('cls')
    else:               # Mac和Linux系统
        os.system('clear')

# 初始化colorama库
init(autoreset=True)

def fetch_ticket_status(url, headers):
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  
    except requests.RequestException as e:
        print(f"请求错误: {e}")
        return None

    # 解析响应数据
    data = response.json()
    tickets = data.get('data', {}).get('screen_list', [])
    if not tickets:
        print("请检查ID输入是否正确")
        return None

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n当前时间: {current_time}")

    table = []
    for screen in tickets:
        screen_name = screen.get('screen_name')  
        for ticket in screen.get('ticket_list', []):
            desc = ticket['desc'] if ticket['desc'] != "普通票" else "普通票"
            sale_status = ticket.get('sale_flag', {}).get('display_name')  
            table.append([screen_name + desc, sale_status])

    return table

# 表格打印函数
def print_ticket_table(table):
    if not table:
        return

    # 计算每列的最大宽度
    max_desc_len = max(len(row[0]) for row in table)
    max_status_len = max(len(row[1]) for row in table)

    # 打印表头
    header = f"{Fore.CYAN}{'票种'.ljust(max_desc_len)}{'状态'.ljust(max_status_len)}{Style.RESET_ALL}"
    print(header)
    print('-' * (max_desc_len + max_status_len))

    # 打印表格内容
    for row in table:
        desc = Fore.YELLOW + row[0].ljust(max_desc_len) + Style.RESET_ALL
        status = Fore.GREEN + row[1].ljust(max_status_len) + Style.RESET_ALL
        print(f"{desc}\t{status}")

# 主程序循环
url = "https://show.bilibili.com/api/ticket/project/getV2?version=134&id=替换为票务ID"  
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
}

while True:
    table = fetch_ticket_status(url, headers)
    if table:
        print_ticket_table(table)
    time.sleep(1)  # 可以根据需要调整请求的频率，太快容易被412风控
    clear_screen()

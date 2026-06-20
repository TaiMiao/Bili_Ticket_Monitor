"""Bili_Ticket_Monitor by TaiMiao & AI """

import time
import threading
import logging
from datetime import datetime
from typing import List, Tuple, Optional
import requests
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning
from colorama import Fore, Style, init
from tabulate import tabulate
from wcwidth import wcswidth

disable_warnings(InsecureRequestWarning)
requests.packages.urllib3.disable_warnings()
init(autoreset=True)

class Config:
    TICKET_ID = "请替换这里"  # 票务ID
    REFRESH_INTERVAL = 1  # 刷新间隔
    TIMEOUT = 10  # 请求超时时间
    API_URL = f"https://show.bilibili.com/api/ticket/project/getV2?version=134&id={TICKET_ID}"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
    }
    ENABLE_LOG = False  # 日志开关：True 启用，False 禁用

# ---------- 日志配置（仅在 ENABLE_LOG 为 True 时初始化） ----------
if Config.ENABLE_LOG:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',  # 精确到秒
        handlers=[
            logging.FileHandler("monitor.log", encoding='utf-8'),
        ]
    )
else:
    # 如果禁用日志，创建一个空 handler 或直接禁用 logger
    logging.getLogger().addHandler(logging.NullHandler())

class StatusColor:
    COLOR_MAP = {
        "已售罄": Fore.RED, "已停售": Fore.RED, "不可售": Fore.RED,
        "未开售": Fore.RED, "暂时售罄": Fore.YELLOW, "预售中": Fore.GREEN
    }
    DEFAULT = Fore.WHITE

def clear_screen():
    print("\033c", end="")

def process_data(json_data: dict) -> Tuple[Optional[str], Optional[List[List[str]]]]:
    data = json_data.get('data', {})
    if not data:
        return None, None

    name = data.get('name', '')
    tickets = [
        [f"{t.get('screen_name', '')} {t.get('desc', '')}".strip(),
         t.get('sale_flag', {}).get('display_name', '')]
        for screen in data.get('screen_list', [])
        for t in screen.get('ticket_list', [])
    ]
    return name, tickets or None

def show_table(name: str, tickets: List[List[str]], pause_event: threading.Event = None):
    if pause_event:
        pause_event.set()

    col1 = max(wcswidth(row[0]) for row in tickets)
    col2 = max(len(row[1]) for row in tickets)

    print(f"\n{Style.BRIGHT}{name}")
    print(f"{Fore.CYAN}{'票种'.ljust(col1)}{'状态'.rjust(col2)}")
    print('-' * (col1 + col2 + 8))
    
    formatted = [
        [row[0].ljust(col1), 
        f"{StatusColor.COLOR_MAP.get(row[1], StatusColor.DEFAULT)}{row[1]}{Style.RESET_ALL}"]
        for row in tickets
    ]
    print(tabulate(formatted, tablefmt='plain'))

    if pause_event:
        pause_event.clear()

def log_ticket_changes(old_tickets: Optional[List[List[str]]], new_tickets: List[List[str]]):
    """比较新旧票务列表，记录变动（新增、状态变更、移除）"""
    if not Config.ENABLE_LOG:
        return  # 日志关闭，直接返回

    if old_tickets is None:
        logging.info(f"[Ticket {Config.TICKET_ID}] 首次加载，共 {len(new_tickets)} 个票种")
        return

    old_dict = {name: status for name, status in old_tickets}
    new_dict = {name: status for name, status in new_tickets}

    # 新增票种
    for name, status in new_tickets:
        if name not in old_dict:
            logging.info(f"[Ticket {Config.TICKET_ID}] 新增票种: {name} -> {status}")

    # 状态变化（原为“票种变化”，改为“状态变化”）
    for name, status in new_tickets:
        if name in old_dict and old_dict[name] != status:
            logging.info(f"[Ticket {Config.TICKET_ID}] 状态变化: {name} 从 {old_dict[name]} 变为 {status}")

    # 移除票种（通常不会发生，但记录以防万一）
    for name, status in old_tickets:
        if name not in new_dict:
            logging.info(f"[Ticket {Config.TICKET_ID}] 移除票种: {name} (原状态 {status})")

class Monitor:
    def __init__(self):
        self.stop = threading.Event()
        self.pause = threading.Event()
        self.last_data = None
        self.healthy = True

    def start(self):
        time_thread = threading.Thread(target=self.show_time, daemon=True)
        monitor_thread = threading.Thread(target=self.run_monitor, daemon=True)
        
        time_thread.start()
        monitor_thread.start()

        try:
            while time_thread.is_alive() or monitor_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop.set()

    def show_time(self):
        current = ""
        while not self.stop.is_set():
            if not self.pause.is_set():
                new_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                if new_time != current:
                    print(f"{Fore.GREEN}当前时间: {new_time}", end='\r')
                    current = new_time
            time.sleep(0.1)

    def run_monitor(self):
        with requests.Session() as s:
            s.verify = False
            s.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))

            while not self.stop.is_set():
                try:
                    resp = s.get(Config.API_URL, headers=Config.HEADERS, timeout=Config.TIMEOUT)
                    resp.raise_for_status()
                    
                    name, tickets = process_data(resp.json())
                    if not tickets:
                        continue

                    # 检测票务变动并记录日志（仅在启用日志时）
                    if self.last_data is not None:
                        log_ticket_changes(self.last_data, tickets)
                    elif Config.ENABLE_LOG:
                        # 首次加载记录一条信息
                        logging.info(f"[Ticket {Config.TICKET_ID}] 监控启动，当前共 {len(tickets)} 个票种")

                    # 刷新表格（无论是否健康，都使用 show_table 不清屏）
                    if not self.healthy:
                        show_table(name, tickets, self.pause)
                    elif tickets != self.last_data:
                        show_table(name, tickets, self.pause)

                    self.last_data = tickets
                    self.healthy = True

                except requests.exceptions.HTTPError as e:
                    status_code = e.response.status_code
                    if status_code == 412:
                        self.handle_error("触发风控！立即停止！", True)
                    elif status_code == 429:
                        self.handle_error("流量限制 (429)", False)
                    else:
                        self.handle_error(f"HTTP错误 {status_code}", False)
                
                except requests.exceptions.RequestException as e:
                    self.handle_error(f"请求异常: {e}", False)
                
                time.sleep(Config.REFRESH_INTERVAL)

    def full_display(self, name, tickets):
        # 此方法保留但不再使用（不清屏策略）
        clear_screen()
        print(f"{Fore.YELLOW}监控ID: {Config.TICKET_ID} | 刷新间隔: {Config.REFRESH_INTERVAL}s")
        print("=" * 40)
        show_table(name, tickets, self.pause)

    def handle_error(self, msg, critical):
        # 记录错误日志（仅在启用日志时）
        if Config.ENABLE_LOG:
            logging.error(f"[Ticket {Config.TICKET_ID}] {msg}")
        print(Fore.RED + f"\n{msg}")
        self.healthy = False
        if critical:
            self.stop.set()

if __name__ == "__main__":
    clear_screen()
    print(f"{Fore.CYAN}项目github页面：https://github.com/TaiMiao/Bili_Ticket_Monitor \n")
    print(f"{Fore.YELLOW}监控ID: {Config.TICKET_ID} | 刷新间隔: {Config.REFRESH_INTERVAL}s")
    print("=" * 40)
    if Config.ENABLE_LOG:
        logging.info(f"[Ticket {Config.TICKET_ID}] 程序启动")
    Monitor().start()
    input("\n按回车键退出程序...\n")

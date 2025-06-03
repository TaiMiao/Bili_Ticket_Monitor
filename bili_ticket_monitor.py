"""Bili_Ticket_Monitor by TaiMiao & AI """

import time
import threading
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
    TIMEOUT = 50  # 请求超时时间
    API_URL = f"https://show.bilibili.com/api/ticket/project/getV2?version=134&id={TICKET_ID}"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
    }

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
        [f"{t.get('screen_name', '')} {t.get('desc', '')}", 
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

                    if not self.healthy:
                        self.full_display(name, tickets)
                    elif tickets != self.last_data:
                        show_table(name, tickets, self.pause)

                    self.last_data = tickets
                    self.healthy = True

                except requests.exceptions.HTTPError as e:
                    self.handle_error("HTTP错误" if e.response.status_code != 412 else "触发风控！立即停止！", e.response.status_code == 412)
                except requests.exceptions.RequestException as e:
                    self.handle_error(f"请求异常: {e}", False)
                
                time.sleep(Config.REFRESH_INTERVAL)

    def full_display(self, name, tickets):
        clear_screen()
        print(f"{Fore.YELLOW}监控ID: {Config.TICKET_ID} | 刷新间隔: {Config.REFRESH_INTERVAL}s")
        print("=" * 40)
        show_table(name, tickets, self.pause)

    def handle_error(self, msg, critical):
        print(Fore.RED + f"\n{msg}")
        self.healthy = False
        if critical:
            self.stop.set()

if __name__ == "__main__":
    clear_screen()
    print(f"{Fore.CYAN}项目github页面：https://github.com/TaiMiao/Bili_Ticket_Monitor \n")
    print(f"{Fore.YELLOW}监控ID: {Config.TICKET_ID} | 刷新间隔: {Config.REFRESH_INTERVAL}s")
    print("=" * 40)
    Monitor().start()
    input("\n按回车键退出程序...\n")

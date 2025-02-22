"""Bili_Ticket_Monitor by TaiMiao & AI"""

import time
import random
import threading
from datetime import datetime
from typing import List, Tuple, Optional, Dict
import requests
from colorama import Fore, Style, init
from tabulate import tabulate
from wcwidth import wcswidth

init(autoreset=True)  # 初始化colorama


class Config:  # pylint: disable=too-few-public-methods
    """票务监控配置参数"""
    TICKET_ID = "请替换此处"  # 实际票务ID
    REFRESH_INTERVAL = 1     # 刷新间隔（秒）
    TIMEOUT = 50             # 请求超时时间
    MAX_RETRIES = 3          # 最大重试次数
    API_BASE_URL = "https://show.bilibili.com/api/ticket/project/getV2"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
        )
    }


class StatusColor:  # pylint: disable=too-few-public-methods
    """票务状态颜色映射配置"""
    MAPPING: Dict[str, str] = {
        "已售罄": Fore.RED,
        "已停售": Fore.RED,
        "不可售": Fore.RED,
        "未开售": Fore.RED,
        "暂时售罄": Fore.YELLOW,
        "预售中": Fore.GREEN,
    }
    DEFAULT = Fore.WHITE


def clear_screen() -> None:
    """使用ANSI转义序列清除屏幕"""
    print("\033c", end="")


def build_api_url() -> str:
    """构建API请求URL"""
    return f"{Config.API_BASE_URL}?version=134&id={Config.TICKET_ID}"


def fetch_data(
    max_retries: int = Config.MAX_RETRIES,
    pause_event: Optional[threading.Event] = None
) -> Tuple[Optional[str], Optional[List[List[str]]]]:
    """获取并处理票务数据"""
    for attempt in range(max_retries):
        try:
            response = requests.get(
                build_api_url(),
                headers=Config.HEADERS,
                timeout=Config.TIMEOUT
            )
            response.raise_for_status()
            return process_response_data(response.json())

        except requests.RequestException as err:
            if not handle_request_exception(err, attempt, max_retries, pause_event):
                return None, None
    return None, None


def process_response_data(json_data: dict) -> Tuple[Optional[str], Optional[List[List[str]]]]:
    """处理API响应数据"""
    data = json_data.get('data', {})
    if not data:
        return None, None

    project_name = data.get('name', '')
    tickets = []

    for screen in data.get('screen_list', []):
        for ticket in screen.get('ticket_list', []):
            ticket_info = [
                f"{ticket.get('screen_name', '')} {ticket.get('desc', '')}",
                ticket.get('sale_flag', {}).get('display_name', '')
            ]
            tickets.append(ticket_info)

    return project_name, tickets if tickets else None


def handle_request_exception(
    err: Exception,
    attempt: int,
    max_retries: int,
    pause_event: Optional[threading.Event]
) -> bool:
    """处理请求异常，返回是否继续重试"""
    if pause_event:
        pause_event.set()

    if isinstance(err, requests.HTTPError) or getattr(err, 'status_code', 0) == 412:
        print(Fore.RED + "\nIP可能被业务风控，请立即停止操作！")
        raise SystemExit(1) from err

    print(Fore.RED + f"\n请求错误: {str(err)}")

    if attempt < max_retries - 1:
        apply_backoff_strategy(attempt)
        return True
    return False


def apply_backoff_strategy(attempt: int) -> None:
    """应用指数退避策略"""
    base_delay = 2 ** attempt
    jitter = random.uniform(0, 1)
    delay = base_delay + jitter
    print(Fore.YELLOW + f"等待 {delay:.2f} 秒后重试 ({attempt + 1}/{Config.MAX_RETRIES})")
    time.sleep(delay)


def display_table(
    name: str,
    tickets: List[List[str]],
    pause_event: Optional[threading.Event] = None
) -> None:
    """显示票务信息表格"""
    if pause_event:
        pause_event.set()

    # 计算列宽
    max_desc = max(calc_width(row[0]) for row in tickets)
    max_status = max(len(row[1]) for row in tickets)

    # 构建表格数据
    table_data = [
        [row[0].ljust(max_desc), colorize_status(row[1])]
        for row in tickets
    ]

    # 打印表格
    print(f"\n{Style.BRIGHT}{name}")
    print(f"{Fore.CYAN}{'票种'.ljust(max_desc)}{'状态'.rjust(max_status)}")
    print('-' * (max_desc + max_status + 8))
    print(tabulate(table_data, tablefmt='plain'))

    if pause_event:
        pause_event.clear()


def calc_width(text: str) -> int:
    """计算文本显示宽度"""
    return wcswidth(text)


def colorize_status(status: str) -> str:
    """为状态添加颜色"""
    color = StatusColor.MAPPING.get(status, StatusColor.DEFAULT)
    return f"{color}{status}{Style.RESET_ALL}"


class MonitorController:
    """监控控制器"""
    def __init__(self):
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.last_state: Optional[List[List[str]]] = None

    def start(self) -> None:
        """启动监控"""
        threads = [
            threading.Thread(target=self.time_display, daemon=True),
            threading.Thread(target=self.monitor, daemon=True)
        ]

        for thread in threads:
            thread.start()
            time.sleep(0.5)  # 错开线程启动

        try:
            while any(t.is_alive() for t in threads):
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop_event.set()

    def time_display(self) -> None:
        """时间显示线程"""
        last_time = ""
        while not self.stop_event.is_set():
            if not self.pause_event.is_set():
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                if current_time != last_time:
                    print(f"{Fore.GREEN}当前时间: {current_time}", end='\r')
                    last_time = current_time
            time.sleep(0.1)

    def monitor(self) -> None:
        """监控线程"""
        name, tickets = fetch_data(pause_event=self.pause_event)
        if not tickets:
            self.stop_event.set()
            return

        display_table(name, tickets, self.pause_event)
        self.last_state = tickets

        while not self.stop_event.is_set():
            time.sleep(Config.REFRESH_INTERVAL)
            name, new_tickets = fetch_data(pause_event=self.pause_event)

            if new_tickets and new_tickets != self.last_state:
                display_table(name, new_tickets, self.pause_event)
                self.last_state = new_tickets


if __name__ == "__main__":
    controller = MonitorController()
    controller.start()
    input("\n按回车键退出...\n")
    

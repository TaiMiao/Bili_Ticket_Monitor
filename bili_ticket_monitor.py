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

# 全局禁用SSL警告
disable_warnings(InsecureRequestWarning)
requests.packages.urllib3.disable_warnings()  # pylint: disable=no-member

init(autoreset=True)


class Config:  # pylint: disable=too-few-public-methods
    """项目配置类，包含API相关参数和请求头设置
    
    Attributes:
        TICKET_ID: 票务项目ID
        REFRESH_INTERVAL: 刷新间隔(秒)
        TIMEOUT: 请求超时时间
        MAX_RETRIES: 最大重试次数
        API_BASE_URL: 基础API地址
        HEADERS: 请求头配置
    """
    TICKET_ID = "请替换这里"
    REFRESH_INTERVAL = 1
    TIMEOUT = 50
    MAX_RETRIES = 3
    API_BASE_URL = "https://show.bilibili.com/api/ticket/project/getV2"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
    }


class StatusColor:  # pylint: disable=too-few-public-methods
    """票务状态颜色映射配置"""
    MAPPING = {
        "已售罄": Fore.RED,
        "已停售": Fore.RED,
        "不可售": Fore.RED,
        "未开售": Fore.RED,
        "暂时售罄": Fore.YELLOW,
        "预售中": Fore.GREEN,
    }
    DEFAULT = Fore.WHITE


def clear_screen() -> None:
    """清空控制台屏幕"""
    print("\033c", end="")


def build_api_url() -> str:
    """构建API请求地址"""
    return f"{Config.API_BASE_URL}?version=134&id={Config.TICKET_ID}"


def process_response_data(json_data: dict) -> Tuple[Optional[str], Optional[List[List[str]]]]:
    """处理API响应数据
    
    Args:
        json_data: 原始JSON响应数据
        
    Returns:
        Tuple: (项目名称, 票务信息列表)
    """
    data = json_data.get('data', {})
    if not data:
        return None, None

    project_name = data.get('name', '')
    tickets = []
    for screen in data.get('screen_list', []):
        for ticket in screen.get('ticket_list', []):
            tickets.append([
                f"{ticket.get('screen_name', '')} {ticket.get('desc', '')}",
                ticket.get('sale_flag', {}).get('display_name', '')
            ])
    return project_name, tickets if tickets else None


def display_table(name: str, tickets: List[List[str]], pause_event: threading.Event = None) -> None:
    """显示票务状态表格
    
    Args:
        name: 项目名称
        tickets: 票务数据
        pause_event: 线程暂停事件
    """
    if pause_event:
        pause_event.set()

    max_desc = max(wcswidth(row[0]) for row in tickets)
    max_status = max(len(row[1]) for row in tickets)

    table_data = [
        [row[0].ljust(max_desc),
         f"{StatusColor.MAPPING.get(row[1], StatusColor.DEFAULT)}{row[1]}{Style.RESET_ALL}"]
        for row in tickets
    ]

    print(f"\n{Style.BRIGHT}{name}")
    print(f"{Fore.CYAN}{'票种'.ljust(max_desc)}{'状态'.rjust(max_status)}")
    print('-' * (max_desc + max_status + 8))
    print(tabulate(table_data, tablefmt='plain'))

    if pause_event:
        pause_event.clear()


class MonitorController:
    """票务监控控制器"""
    def __init__(self):
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.last_state = None
        self.last_fetch_success = True

    def start(self) -> None:
        """启动监控线程"""
        threads = [
            threading.Thread(target=self.time_display, daemon=True),
            threading.Thread(target=self.monitor, daemon=True)
        ]
        for t in threads:
            t.start()
            time.sleep(0.5)
        try:
            while any(t.is_alive() for t in threads):
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop_event.set()

    def time_display(self) -> None:
        """实时时间显示线程"""
        last_time = ""
        while not self.stop_event.is_set():
            if not self.pause_event.is_set():
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                if current_time != last_time:
                    print(f"{Fore.GREEN}当前时间: {current_time}", end='\r')
                    last_time = current_time
            time.sleep(0.1)

    def monitor(self) -> None:
        """票务监控主线程"""
        with requests.Session() as session:
            session.verify = False  # 禁用证书验证
            adapter = requests.adapters.HTTPAdapter(max_retries=3)
            session.mount('https://', adapter)

            while not self.stop_event.is_set():
                try:
                    response = session.get(
                        build_api_url(),
                        headers=Config.HEADERS,
                        timeout=Config.TIMEOUT
                    )
                    response.raise_for_status()
                    name, tickets = process_response_data(response.json())

                    if not tickets:
                        continue

                    if not self.last_fetch_success:
                        self._display_full_interface(name, tickets)
                    elif tickets != self.last_state:
                        display_table(name, tickets, self.pause_event)

                    self.last_state = tickets
                    self.last_fetch_success = True

                except requests.exceptions.HTTPError as err:
                    # 412风控处理
                    if err.response.status_code == 412:
                        self._handle_error("可能遭到风控，请立即停止操作！", is_critical=True)
                    else:
                        self._handle_error(f"HTTP错误: {err}", is_critical=False)
                    self.last_fetch_success = False
                except requests.exceptions.RequestException as err:
                    self._handle_error(f"请求错误: {err}", is_critical=False)
                    self.last_fetch_success = False

                time.sleep(Config.REFRESH_INTERVAL)

    def _display_full_interface(self, name: str, tickets: List[List[str]]) -> None:
        """显示完整界面"""
        clear_screen()
        print(f"{Fore.YELLOW}监控ID: {Config.TICKET_ID} | 刷新间隔: {Config.REFRESH_INTERVAL}s")
        print("=" * 40)
        display_table(name, tickets, self.pause_event)

    def _handle_error(self, message: str, is_critical: bool) -> None:
        """处理错误信息"""
        print(Fore.RED + f"\n{message}")
        if is_critical:
            self.stop_event.set()


if __name__ == "__main__":
    clear_screen()
    print(f"{Fore.YELLOW}监控ID: {Config.TICKET_ID} | 刷新间隔: {Config.REFRESH_INTERVAL}s")
    print("=" * 40)
    controller = MonitorController()
    try:
        controller.start()
    finally:
        input("\n按回车键退出程序...\n")

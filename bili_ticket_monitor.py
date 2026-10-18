"""Bili_Ticket_Monitor by TaiMiao & AI"""

from __future__ import annotations

import argparse
import logging
import os
import random
import re
import shutil
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Sequence


def _pause(message: str = "按回车键退出程序...") -> None:
    """双击启动时窗口会随进程一起消失，出错后停一下，别让人只看到闪一下。"""
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input(f"\n{message}\n")
    except (EOFError, KeyboardInterrupt):
        pass


def _write_crash_log(detail: str) -> str:
    path = Path(os.environ.get("TEMP") or Path.home()) / "bili_ticket_monitor_crash.log"
    try:
        path.write_text(
            f"{datetime.now():%Y-%m-%d %H:%M:%S}\n{detail}\n",
            encoding="utf-8",
            errors="replace",
        )
        return str(path)
    except OSError:
        return ""


try:
    import requests
    from colorama import Fore, Style, init
    from urllib3 import disable_warnings
    from urllib3.exceptions import InsecureRequestWarning
    from urllib3.util.retry import Retry
    from wcwidth import wcswidth
except ImportError as exc:  # 换机器 / 换了 Python 时最常见的「双击闪退」原因
    print(f"[错误] 缺少依赖：{exc}")
    print(f"[错误] 当前解释器：{sys.executable}")
    print("请在该解释器下执行：pip install -r requirements.txt")
    _write_crash_log(f"ImportError: {exc}\n解释器: {sys.executable}\n")
    _pause()
    raise SystemExit(1) from exc

# 版本号与 metadata.yaml / exe 保持一致，固定 1.1.4.5
__version__ = "1.1.4.5"

disable_warnings(InsecureRequestWarning)
init(autoreset=True)


# ---------------- 配置 ----------------
class Config:
    """默认配置。打包前通常只需要改 TICKET_ID / ENABLE_LOG。"""

    TICKET_ID = "1001701"  # 票务 ID
    API_URL = (
        "https://show.bilibili.com/api/ticket/project/getV2"
        "?version=134&id={ticket_id}"
    )

    REFRESH_INTERVAL = 2.0  # 轮询间隔（秒），实际间隔会叠加 ±JITTER_RATIO 抖动
    JITTER_RATIO = 0.3  # 抖动比例，0 表示固定间隔
    TIMEOUT = 10.0  # 单次请求超时（秒）

    ENABLE_LOG = False  # 日志开关
    LOG_FILE = "monitor.log"  # 日志文件（相对启动目录）
    LOG_MAX_BYTES = 5 * 1024 * 1024  # 单个日志文件上限
    LOG_BACKUP_COUNT = 3  # 轮转保留份数

    CONFIRM_UPDATES = 2  # 连续 N 次轮询一致，才确认为「状态变化」
    CONFIRM_REMOVALS = 2  # 连续 N 次轮询缺失，才确认为「移除」
    MAX_BACKOFF = 60.0  # 出错退避上限（秒）

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
    }


class StatusColor:
    COLOR_MAP = {
        "已售罄": Fore.RED,
        "已停售": Fore.RED,
        "不可售": Fore.RED,
        "未开售": Fore.RED,
        "暂时售罄": Fore.YELLOW,
        "预售中": Fore.GREEN,
    }
    DEFAULT = Fore.WHITE



# ---------------- 文本/宽度工具 ----------------
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def text_width(text: str) -> int:
    """按终端显示宽度计算（中文 = 2 列，ANSI 转义不占位）。"""
    plain = _ANSI_RE.sub("", text)
    width = wcswidth(plain)
    return width if width >= 0 else len(plain)


def pad(text: str, width: int, align: str = "left") -> str:
    fill = " " * max(0, width - text_width(text))
    return text + fill if align == "left" else fill + text


def fit(text: str, width: int) -> str:
    """按显示宽度截断，超长以省略号结尾；着色文本会保留转义并在末尾复位。"""
    if width <= 0:
        return ""
    if text_width(text) <= width:
        return text

    limit = width - 1
    kept: list[str] = []
    used = 0
    index = 0
    while index < len(text) and used < limit:
        match = _ANSI_RE.match(text, index)
        if match:  # 转义序列原样保留，不占显示宽度
            kept.append(match.group())
            index = match.end()
            continue
        char_width = wcswidth(text[index])
        char_width = char_width if char_width >= 0 else 1
        if used + char_width > limit:
            break
        kept.append(text[index])
        used += char_width
        index += 1
    kept.append("…")
    if _ANSI_RE.search(text):
        kept.append(Style.RESET_ALL)
    return "".join(kept)


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


# ---------------- 数据模型 ----------------
@dataclass(frozen=True)
class Ticket:
    screen: str
    desc: str
    status: str

    @property
    def name(self) -> str:
        return f"{self.screen} {self.desc}".strip()

    @property
    def key(self) -> tuple[str, str]:
        return (self.screen, self.desc)


@dataclass(frozen=True)
class Change:
    kind: str  # 新增 / 状态变化 / 移除
    screen: str
    desc: str
    old: str
    new: str

    @property
    def name(self) -> str:
        return f"{self.screen} {self.desc}".strip()


def describe_change(change: Change) -> str:
    if change.kind == "新增":
        return f"新增票种: {change.name} -> {change.new}"
    if change.kind == "移除":
        return f"移除票种: {change.name} (原状态 {change.old})"
    return f"状态变化: {change.name} 从 {change.old} 变为 {change.new}"


class ApiError(RuntimeError):
    """接口返回了非预期的内容。"""


_SPACE_RE = re.compile(r"[ \t\u00a0\u3000]+")


def clean_text(value: object, *, limit: int = 120) -> str:
    """把接口里的字符串收拾干净：全角/不换行空格归一，连续空白压成一个。"""
    text = _SPACE_RE.sub(" ", str(value if value is not None else "")).strip()
    return text[:limit]


def _ticket_status(item: dict) -> str:
    """sale_flag 绝大多数时候是 {"display_name": ...}，少数项目会直接给字符串。"""
    flag = item.get("sale_flag")
    if isinstance(flag, dict):
        status = clean_text(flag.get("display_name"), limit=32)
    elif isinstance(flag, str):
        status = clean_text(flag, limit=32)
    else:
        status = ""
    return status or "未知"



def parse_tickets(payload: object) -> tuple[str, list[Ticket]]:
    """把接口 JSON 摊平成 Ticket 列表；场次名参与命名，避免重名票种互相覆盖。"""
    if not isinstance(payload, dict):
        raise ApiError("接口返回的不是 JSON 对象")

    code = payload.get("code")
    if payload.get("success") is False or code not in (0, None):
        raise ApiError(f"接口返回错误 code={code} message={payload.get('message')}")

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise ApiError("接口 data 字段格式异常")

    name = clean_text(data.get("name"), limit=80) or "未知项目"
    tickets: list[Ticket] = []
    seen: set[tuple[str, str]] = set()

    screens = data.get("screen_list")
    if isinstance(screens, list):
        for screen in screens:
            if not isinstance(screen, dict):
                continue
            screen_name = clean_text(screen.get("name") or screen.get("screen_name"))
            items = screen.get("ticket_list")
            if isinstance(items, list):
                for item in items:
                    _add_ticket(tickets, seen, screen_name, item)

    # 真实数据挂在 screen_list 下，ticket_list 恒为空；换版本时也可能直接用这一层。
    items = data.get("ticket_list")
    if isinstance(items, list):
        for item in items:
            _add_ticket(tickets, seen, "", item)

    return name, tickets


def _add_ticket(
    tickets: list[Ticket], seen: set[tuple[str, str]], screen_name: str, item: object
) -> None:
    if not isinstance(item, dict):
        return
    desc = clean_text(item.get("desc") or item.get("name"))
    if not desc:
        return
    ticket = Ticket(screen_name, desc, _ticket_status(item))
    if ticket.key in seen:  # 同场次同名的重复行会让去抖计数混乱，只留第一条
        return
    seen.add(ticket.key)
    tickets.append(ticket)


class TicketBoard:
    """维护「已确认的票种状态」，把服务端秒级抖动过滤掉。"""

    def __init__(self, confirm_updates: int = 2, confirm_removals: int = 2) -> None:
        self.confirm_updates = max(1, confirm_updates)
        self.confirm_removals = max(1, confirm_removals)
        self._confirmed: dict[tuple[str, str], Ticket] = {}
        self._pending: dict[tuple[str, str], tuple[str, int]] = {}
        self._missing: dict[tuple[str, str], int] = {}
        self.ready = False

    @property
    def pending(self) -> int:
        return len(self._pending) + len(self._missing)

    def seed(self, tickets: Sequence[Ticket]) -> None:
        self._confirmed = {ticket.key: ticket for ticket in tickets}
        self._pending.clear()
        self._missing.clear()
        self.ready = True

    def update(self, tickets: Sequence[Ticket]) -> list[Change]:
        """喂入一次观测结果，返回本次「确认成立」的变动。"""
        current = {ticket.key: ticket for ticket in tickets}
        if not self.ready:
            self.seed(tickets)
            return []

        changes: list[Change] = []
        for key, ticket in current.items():
            known = self._confirmed.get(key)
            if known is None:
                if self._confirm(key, ticket.status):
                    self._confirmed[key] = ticket
                    changes.append(Change("新增", ticket.screen, ticket.desc, "", ticket.status))
            elif known.status != ticket.status:
                if self._confirm(key, ticket.status):
                    self._confirmed[key] = ticket
                    changes.append(
                        Change("状态变化", ticket.screen, ticket.desc, known.status, ticket.status)
                    )
            else:
                self._pending.pop(key, None)

        for key, known in list(self._confirmed.items()):
            if key in current:
                self._missing.pop(key, None)
                continue
            count = self._missing.get(key, 0) + 1
            if count >= self.confirm_removals:
                self._missing.pop(key, None)
                self._pending.pop(key, None)
                del self._confirmed[key]
                changes.append(Change("移除", known.screen, known.desc, known.status, ""))
            else:
                self._missing[key] = count

        return changes

    def _confirm(self, key: tuple[str, str], status: str) -> bool:
        pending = self._pending.get(key)
        count = pending[1] + 1 if pending and pending[0] == status else 1
        if count >= self.confirm_updates:
            self._pending.pop(key, None)
            return True
        self._pending[key] = (status, count)
        return False


# ---------------- 终端输出 ----------------
class Console:
    """线程安全输出；支持 ANSI 时整块就地重绘，避免刷屏。"""

    def __init__(self, *, redraw: bool = True, stream=None) -> None:
        self.stream = stream or sys.stdout
        self.lock = threading.RLock()
        self._block_height = 0
        self._line_width = 0
        self._inplace = redraw and self._is_tty()

    def _is_tty(self) -> bool:
        try:
            return bool(self.stream.isatty())
        except (AttributeError, ValueError):
            return False

    def write(self, text: str) -> None:
        with self.lock:
            self.stream.write(self._encode_safe(text))
            self.stream.flush()

    def _encode_safe(self, text: str) -> str:
        """控制台编码可能不是 UTF-8（例如 GBK），保证不会因个别字符崩掉。"""
        encoding = getattr(self.stream, "encoding", None)
        if not encoding:
            return text
        try:
            text.encode(encoding)
        except (LookupError, UnicodeEncodeError):
            return text.encode(encoding, "replace").decode(encoding, "replace")
        return text

    def clear(self) -> None:
        with self.lock:
            if self._inplace:
                self.stream.write("\033[2J\033[H")
            self._block_height = 0
            self.stream.flush()

    @property
    def inplace(self) -> bool:
        """是否会用 ANSI 就地重绘（非 tty 或 --no-redraw 时为 False）。"""
        return self._inplace

    @staticmethod
    def _height(block: Sequence[str]) -> int:
        columns = max(20, shutil.get_terminal_size((100, 24)).columns)
        # 长行会被终端折行，占用的「实际行数」必须计入光标上移量
        return sum(max(1, -(-text_width(line) // columns)) for line in block)

    def fits(self, lines: Sequence[str]) -> bool:
        """整块能否安全地就地覆盖（不会顶进滚动区）。"""
        return self._inplace and not self._too_tall(self._height(lines))

    def render(self, lines: Sequence[str]) -> None:
        block = list(lines)
        with self.lock:
            height = self._height(block)
            # 下面若停着未换行的状态行，回表体首行要多上移一行
            open_line = self._line_width > 0
            up = self._block_height + (1 if open_line else 0)
            tail_width = self._line_width
            self._line_width = 0

            if not self._inplace or self._too_tall(height):
                # 内容高于窗口时无法安全地向上覆盖，退化为顺序输出
                self._block_height = 0
                self.stream.write(self._encode_safe("\n".join(block) + "\n"))
                self.stream.flush()
                return

            buffer = [f"\033[{up}A"] if up else []
            for line in block:
                buffer.append("\033[2K" + line + "\n")
            # 擦掉上一帧多出来的行，再把光标提回块底，否则每次重绘都会往下漂
            pad = max(0, self._block_height - height)
            for _ in range(pad):
                buffer.append("\033[2K\n")
            if pad:
                buffer.append(f"\033[{pad}A")
            self.stream.write(self._encode_safe("".join(buffer)))
            self.stream.flush()
            self._block_height = height
            # 记下尾巴宽度，交给 update_line 用空格擦
            self._line_width = tail_width if open_line else 0

    def update_line(self, text: str) -> None:
        """原地刷新同一行（表格比窗口高时，用它代替每轮打印整表）。"""
        width = text_width(text)
        with self.lock:
            if not self._inplace:
                self.stream.write(self._encode_safe(text) + "\n")
                self.stream.flush()
                return
            head = "\r" if self._line_width else ""
            tail = " " * max(0, self._line_width - width)  # 空格擦掉上一行残留
            self.stream.write(head + self._encode_safe(text) + tail)
            self.stream.flush()
            self._line_width = width

    def end_line(self) -> None:
        """结束原地刷新的那一行，让后续输出从新行开始。"""
        with self.lock:
            if self._line_width:
                self.stream.write("\n")
                self.stream.flush()
                self._line_width = 0

    @staticmethod
    def _too_tall(height: int) -> bool:
        terminal_lines = shutil.get_terminal_size((100, 24)).lines
        # 整块离窗口底边太近时，下一帧的光标上移会因滚动而错位
        return height + 2 > max(8, terminal_lines)


# ---------------- 日志 ----------------
def setup_logging(settings: "Settings") -> logging.Logger:
    logger = logging.getLogger("bili_ticket_monitor")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()
    if not settings.log_enabled:
        logger.addHandler(logging.NullHandler())
        return logger

    handler = RotatingFileHandler(
        settings.log_file,
        maxBytes=Config.LOG_MAX_BYTES,
        backupCount=Config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    return logger


# ---------------- 运行参数 ----------------
@dataclass(frozen=True)
class Settings:
    ticket_id: str
    api_url: str
    interval: float
    timeout: float
    log_enabled: bool
    log_file: str
    redraw: bool
    max_polls: int

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "Settings":
        api_url = args.api_url or Config.API_URL.format(ticket_id=args.ticket_id)
        return cls(
            ticket_id=str(args.ticket_id),
            api_url=api_url,
            interval=max(0.1, float(args.interval)),
            timeout=max(1.0, float(args.timeout)),
            log_enabled=bool(args.log),
            log_file=str(args.log_file),
            redraw=not args.no_redraw,
            max_polls=max(0, int(args.max_polls)),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "bili_ticket_monitor",
        description="B站会员购余票监测（终端版）",
    )
    parser.add_argument("--ticket-id", default=Config.TICKET_ID, help="票务 ID")
    parser.add_argument(
        "--interval",
        type=float,
        default=Config.REFRESH_INTERVAL,
        help="轮询间隔（秒），默认 %(default)s",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=Config.TIMEOUT,
        help="单次请求超时（秒），默认 %(default)s",
    )
    parser.add_argument(
        "--log",
        action=argparse.BooleanOptionalAction,
        default=Config.ENABLE_LOG,
        help="启用/禁用日志",
    )
    parser.add_argument("--log-file", default=Config.LOG_FILE, help="日志文件路径")
    parser.add_argument("--api-url", default=None, help="覆盖接口地址（调试用）")
    parser.add_argument("--max-polls", type=int, default=0, help="轮询 N 次后退出（0=无限，调试用）")
    parser.add_argument("--no-redraw", action="store_true", help="禁用就地刷新（便于重定向输出）")
    return parser


# ---------------- 监控主体 ----------------
class Monitor:
    def __init__(self, settings: Settings, console: Console, logger: logging.Logger) -> None:
        self.settings = settings
        self.console = console
        self.logger = logger

        self.stop = threading.Event()
        self.fatal = False
        self.board = TicketBoard(Config.CONFIRM_UPDATES, Config.CONFIRM_REMOVALS)

        self.started = time.monotonic()
        self.polls = 0
        self.failures = 0
        self.error_count = 0
        self.last_error = ""
        self.warning = ""
        self.event_name = "正在获取票务信息…"
        self.tickets: list[Ticket] = []
        self._last_frame_key: tuple[object, ...] | None = None
    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        session.verify = False
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.5,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = requests.adapters.HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _fetch(self, session: requests.Session) -> object:
        response = session.get(
            self.settings.api_url,
            headers=Config.HEADERS,
            timeout=self.settings.timeout,
        )
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError(f"响应不是合法 JSON（HTTP {response.status_code}）") from exc
    def run(self) -> None:
        session = self._build_session()
        self.logger.info(f"[Ticket {self.settings.ticket_id}] 程序启动")
        try:
            while not self.stop.is_set():
                self.polls += 1
                self._poll(session)
                self._render()
                if self.stop.is_set():
                    break
                if self.settings.max_polls and self.polls >= self.settings.max_polls:
                    break
                if self.stop.wait(self._delay()):
                    break
        finally:
            self.console.end_line()
            session.close()

    def _poll(self, session: requests.Session) -> None:
        try:
            payload = self._fetch(session)
            name, tickets = parse_tickets(payload)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status == 412:
                self._fail("触发风控！立即停止！", fatal=True)
            elif status == 429:
                # 429 只是被限流，忽略即可：不计错误、不写日志、不退避，下一轮照常请求
                pass
            else:
                self._fail(f"HTTP错误 {status}")
        except requests.Timeout:
            self._fail("请求超时")
        except requests.RequestException as exc:
            self._fail(f"请求异常: {exc}")
        except ApiError as exc:
            self._fail(str(exc))
        except Exception as exc:  # 兜底：任何意外都不让监控线程退出
            self._fail(f"未预期的异常: {type(exc).__name__}: {exc}")
        else:
            self._accept(name, tickets)

    def _accept(self, name: str, tickets: list[Ticket]) -> None:
        self.failures = 0
        self.last_error = ""
        self.event_name = name

        if not tickets:
            # 空列表可能只是接口暂时没返回，不据此判定「移除」，也不重置状态
            self.warning = "接口未返回票种列表"
            self.tickets = []
            return

        self.warning = ""
        self.tickets = tickets
        if not self.board.ready:
            self.board.seed(tickets)
            self.logger.info(
                f"[Ticket {self.settings.ticket_id}] 监控启动，当前共 {len(tickets)} 个票种"
            )
            return

        for change in self.board.update(tickets):
            self.logger.info(f"[Ticket {self.settings.ticket_id}] {describe_change(change)}")

    def _fail(self, message: str, *, fatal: bool = False) -> None:
        self.error_count += 1
        self.failures += 1
        self.last_error = message
        self.logger.error(f"[Ticket {self.settings.ticket_id}] {message}")
        if fatal:
            self.fatal = True
            self.stop.set()

    def _delay(self) -> float:
        if self.failures:
            base = max(self.settings.interval, 1.0)
            delay = min(Config.MAX_BACKOFF, base * (2 ** min(self.failures - 1, 5)))
            return delay
        low = 1.0 - Config.JITTER_RATIO
        high = 1.0 + Config.JITTER_RATIO
        return self.settings.interval * random.uniform(low, high)
    def _render(self) -> None:
        columns = max(40, shutil.get_terminal_size((100, 24)).columns)
        log_state = "开" if self.settings.log_enabled else "关"

        frame = [
            fit(
                f"{Style.BRIGHT}{Fore.CYAN}Bili_Ticket_Monitor"
                f"{Style.RESET_ALL}{Fore.CYAN} | 监控ID {self.settings.ticket_id}"
                f" | 刷新 {self.settings.interval:g}s | 日志 {log_state}{Style.RESET_ALL}",
                columns - 1,
            ),
            "",
            fit(f"{Style.BRIGHT}{self.event_name}{Style.RESET_ALL}", columns - 1),
            *self._table(columns),
        ]

        if self.warning:
            frame.append("")
            frame.append(f"{Fore.YELLOW}[提示] {fit(self.warning, columns - 8)}{Style.RESET_ALL}")
        if self.last_error:
            frame.append("")
            frame.append(f"{Fore.RED}[错误] {fit(self.last_error, columns - 8)}{Style.RESET_ALL}")

        # 状态行单独拿出来：窗口放不下整表时，它是唯一会被原地刷新的那一行
        status = fit(self._status_line(), columns - 1)
        frame.append("")  # 表体与状态行之间留一个空行
        whole = frame + [status]

        if self.console.fits(whole):
            self.console.render(whole)
            self._last_frame_key = None
            return

        # 整表放不下：表体只在内容变化时重印，状态行固定在下面原地刷新
        key = self._frame_key()
        if key != self._last_frame_key:
            self.console.render(frame)
            self._last_frame_key = key
        self.console.update_line(status)

    def _frame_key(self) -> tuple[object, ...]:
        """整表内容快照，用来判断这一轮要不要重绘。"""
        return (
            self.event_name,
            tuple((ticket.key, ticket.status) for ticket in self.tickets),
            self.warning,
            self.last_error,
            self.fatal,
            self.failures,
        )

    def _status_line(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.fatal:
            health = f"{Fore.RED}已停止（风控）{Style.RESET_ALL}"
        elif self.failures:
            health = f"{Fore.YELLOW}重连中（第 {self.failures} 次）{Style.RESET_ALL}"
        else:
            health = f"{Fore.GREEN}正常{Style.RESET_ALL}"

        parts = [
            f"当前时间 {now}",
            f"运行 {format_duration(time.monotonic() - self.started)}",
            f"请求 {self.polls} 次",
            f"错误 {self.error_count} 次",
            f"状态 {health}",
        ]
        if self.board.pending:
            parts.append(f"{Fore.YELLOW}待确认 {self.board.pending}{Style.RESET_ALL}")
        return " | ".join(parts)

    def _table(self, columns: int) -> list[str]:
        tickets = self.tickets
        if not tickets:
            return [f"{Fore.YELLOW}（暂无票种数据）{Style.RESET_ALL}"]

        header = "票种"
        width_status = max([text_width("状态")] + [text_width(t.status) for t in tickets])
        width_name = max([text_width(header)] + [text_width(t.name) for t in tickets])
        # 票种列最多占到「终端宽度 - 状态列 - 间距」，避免折行
        width_name = max(16, min(width_name, max(16, columns - width_status - 3)))

        lines = [
            f"{Fore.CYAN}{pad(header, width_name)}  {pad('状态', width_status, 'right')}"
            f"{Style.RESET_ALL}",
            "-" * min(columns - 1, width_name + 2 + width_status),
        ]
        for ticket in tickets:
            color = StatusColor.COLOR_MAP.get(ticket.status, StatusColor.DEFAULT)
            lines.append(
                f"{pad(fit(ticket.name, width_name), width_name)}  "
                f"{color}{pad(ticket.status, width_status, 'right')}{Style.RESET_ALL}"
            )
        return lines


# ---------------- 入口 ----------------
def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_args(args)
    logger = setup_logging(settings)
    console = Console(redraw=settings.redraw)
    monitor = Monitor(settings, console, logger)

    console.clear()
    console.write(
        f"{Fore.CYAN}项目github页面：https://github.com/TaiMiao/Bili_Ticket_Monitor"
        f"{Style.RESET_ALL}\n"
    )

    crashed = False
    try:
        monitor.run()
    except KeyboardInterrupt:
        monitor.stop.set()
        console.write("\n")
    except Exception:  # 双击运行时至少要留下原因，而不是窗口一闪就没了
        detail = traceback.format_exc()
        crashed = True
        console.write(f"\n{Fore.RED}[错误] 程序异常退出：{Style.RESET_ALL}\n{detail}")
        crash_file = _write_crash_log(detail)
        if crash_file:
            console.write(f"\n错误详情已保存到 {crash_file}\n")

    if monitor.fatal:
        console.write(f"{Fore.RED}程序已因风控停止，请稍后更换网络环境再试。{Style.RESET_ALL}\n")

    _pause()
    return 1 if (monitor.fatal or crashed) else 0


if __name__ == "__main__":
    raise SystemExit(main())

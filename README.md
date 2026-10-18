# Bili_Ticket_Monitor

![进入二次元](https://github.com/user-attachments/assets/7ac8b7c7-3cfd-4438-a7ce-e7ab31dfe19a)

开源免费，实时监测Bilibili会员购漫展演出余票状态(无抢票功能)   
对于脚本有任何问题可以提交issue或联系作者    
TG：https://t.me/TaiMiao_Channel   
   
推荐使用此脚本的漫展(有回流票的大型漫展)：BW (Bilibili World)、BML (Bilibili Macro Link)......  
以上漫展作者将在购票链接公布后第一时间更新exe文件，其余漫展作者会挑选热门的更新

> [!NOTE]
> 本程序依据MIT开源协议公开。   
> 本脚本大部分由 AI 编写。   
> 使用本程序进行违法操作产生的法律责任由操作者自行承担。

# 功能特性

- **轮询带抖动**：默认 2 秒一次，实际间隔在 1.4～2.6 秒之间随机，避免固定频率被风控盯上
- **中文表格不错位**：表格按显示宽度对齐（一个汉字算 2 列），不会因为票种名里混着中英文就歪掉
- **自适应窗口**：票种多到窗口装不下时，表格只在内容变化时重印，底部状态行始终原地刷新，不会把历史表格一行行顶上去
- **日志按大小轮转**：默认单个文件 5 MB，保留 3 份，不会无限长大
- **双击也能看到错误**：崩溃时把堆栈写进 `%TEMP%\bili_ticket_monitor_crash.log` 并停住窗口，不会一闪就没

# 使用教程

本脚本可以使用exe文件直接运行也可以使用源码运行，请根据自身情况选择
   
## 一、直接运行

### 你可以直接下载release中发布的合适的exe文件运行

#### 优点

- 无需安装python
- 无需配置

#### 缺点

- #### 无法覆盖所有漫展/演出
- 无法配置
- 如需监控部分冷门展演请参见``二、源码运行``自行配置

## 二、源码运行

### 0. 确保你有能力使用此脚本

- #### 会用电脑 ####
- ### 会用电脑 ###
- ## 看过并且能理解readme的内容 ##

### 1. 前期准备

- 安装 Python 3.10 或更高版本
- 安装依赖：`pip install -r requirements.txt`

### 2. 找票务 ID

打开 [会员购首页](https://show.bilibili.com/platform/home.html) → 点进你要监控的漫展/演出 → 看地址栏最后的 `id=` 后面那串数字，就是票务 ID。

比如 `https://show.bilibili.com/platform/detail.html?id=1001701` 里，ID 就是 `1001701`。

### 3. 配置

把票务 ID 填进 `bili_ticket_monitor.py` 的 `Config.TICKET_ID`，其余配置按需改：

| 配置项 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `TICKET_ID` | `"1001701"` | 要监控的票务 ID |
| `REFRESH_INTERVAL` | `2.0` | 轮询间隔（秒） |
| `JITTER_RATIO` | `0.3` | 抖动比例，`0` 表示固定间隔 |
| `TIMEOUT` | `10.0` | 单次请求超时（秒） |
| `ENABLE_LOG` | `False` | 是否写日志 |
| `LOG_FILE` | `"monitor.log"` | 日志路径（相对启动目录） |
| `LOG_MAX_BYTES` | `5 MB` | 单个日志文件上限 |
| `LOG_BACKUP_COUNT` | `3` | 轮转保留份数 |
| `CONFIRM_UPDATES` | `2` | 连续几次观测一致才算状态变化 |
| `CONFIRM_REMOVALS` | `2` | 连续几次观测缺失才算票种被移除 |
| `MAX_BACKOFF` | `60.0` | 出错退避上限（秒） |

图片位置示意（旧版截图，配置项位置一致）：

![image](https://github.com/user-attachments/assets/cb075b6c-6212-4b5b-be51-5422d42df097)

### 4. 运行

```bash
python bili_ticket_monitor.py
```

也可以直接用命令行参数覆盖配置，不改代码：

| 参数 | 说明 |
| :--- | :--- |
| `--ticket-id` | 票务 ID |
| `--interval` | 轮询间隔（秒） |
| `--timeout` | 单次请求超时（秒） |
| `--log` / `--no-log` | 启用或禁用日志 |
| `--log-file` | 日志文件路径 |
| `--api-url` | 覆盖接口地址（调试用） |
| `--max-polls` | 轮询 N 次后退出，0 为无限（调试用） |
| `--no-redraw` | 禁用就地刷新，适合把输出重定向到文件 |

几个常见用法：

```bash
# 换个漫展，开日志，5 秒一次
python bili_ticket_monitor.py --ticket-id 1001653 --interval 5 --log

# 只想看 3 次结果就退出
python bili_ticket_monitor.py --max-polls 3

# 输出重定向到文件（不刷屏）
python bili_ticket_monitor.py --no-redraw > out.txt
```

### 5. 效果展示

| 状态 | 颜色 | 含义 |
| :--- | :---: | :--- |
| **未开售** | 🔴红 | 尚未开始销售 |
| **预售中** | 🟢绿 | 处于预售阶段，且有票 |
| **暂时售罄** | 🟡黄 | 当前票量耗尽，短时间内可能因用户超时未支付而释放少量余票 |
| **已售罄** | 🔴红 | 所有票已售罄，短时间内无余票 |
| **已停售** | 🔴红 | 官方已停止该票种的销售 |
| **不可售** | 🔴红 | 该票种因特殊原因不销售 |

### 6. 日志

`ENABLE_LOG` 打开后写入 `monitor.log`，格式与旧版完全一致：

```
2026-10-18 16:29:14 - INFO - [Ticket 1001701] 程序启动
2026-10-18 16:29:14 - INFO - [Ticket 1001701] 监控启动，当前共 12 个票种
2026-10-18 16:31:33 - INFO - [Ticket 1001701] 状态变化: 2026-07-11 周六 S级 从 未开售 变为 预售中
2026-10-18 16:32:40 - ERROR - [Ticket 1001701] 请求失败（HTTP 500），第 1 次
```

# 常见问题

**控制台中文/符号变成问号？**
程序会自动按控制台编码降级显示；个别符号仍显示不出时，可以 `chcp 65001` 切到 UTF-8，或设置环境变量 `PYTHONUTF8=1`。

**能不能抢票？**
不能，这个脚本只做监测。

## 注意事项

- 请求间隔时间太短可能会被业务风控
- 转载此脚本时必须标注出处

#### 祝大家都能有美好的漫展演出体验(っ^_^)っ
   
![回到三次元](https://github.com/user-attachments/assets/81ede360-2f8d-48c1-a384-ffddb7c68e22)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=TaiMiao/Bili_Ticket_Monitor&type=Date)](https://star-history.com/#TaiMiao/Bili_Ticket_Monitor&Date)

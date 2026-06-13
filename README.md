# SHIEP-PreSelection-Script

多账号教务系统数据抓取工具。通过多个 VPN 隧道实现同一设备同时登录多个账号，自动提取 Cookie、成绩与学分完成情况。可以视作是选课脚本的预备脚本

## 功能
- 多账号并发：每个账号绑定独立 VPN 隧道，互不干扰
- Cookie 提取：获取 JSESSIONID、SERVERNAME 等会话信息，为选课脚本[SHIEP-Course-Selection-Script](https://github.com/TEraby-E/SHIEP-Course-Selection-Script)提供基本信息
- 成绩爬取：拉取全部或指定学期的课程成绩
- 学分计划：抓取培养计划完成情况，按大类汇总学分需求与缺额，显示未完成的小类明细

## 环境要求

- Windows 10/11
- Python 3.10+
- [SHIEP-Pipeline](https://github.com/Yan233th/SHIEP-Course-Selection-Script) 上电VPN脚本(Easier Connect)
- 外部代理

## 安装

```powershell
# 安装 Python 依赖(推荐使用uv环境)
pip install playwright pyyaml rich

# 安装 Chromium（国内需设镜像）
set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
playwright install chromium

```

## 配置

复制模板并编辑：

```powershell
copy config.example.yaml config.yaml
```

```yaml
login_url: "https://ids.shiep.edu.cn/authserver/login"
target_url: "https://jw.shiep.edu.cn/eams/stdElectCourse!batchOperator.action?profileId=1776"
cookie_filter: "JSESSIONID,SERVERNAME"
headless: true
timeout: 30
max_concurrency: 4
output: "results.json"
semester: ""  # 留空=全部学期，填学期ID如 "404" 筛选特定学期

accounts:
  - username: "学号1"
    password: "教务密码1"
    proxy: "socks5://127.0.0.1:1081"
  - username: "学号2"
    password: "教务密码2"
    proxy: "socks5://127.0.0.1:1082"
  - username: "学号3"
    password: "教务密码3"
    proxy: "socks5://127.0.0.1:1083"
  - username: "学号4"
    password: "教务密码4"
    proxy: "socks5://127.0.0.1:1084"
```

## 使用

### 1. 启动 VPN 隧道

编辑 `launch_vpns.txt` 填入 VPN 账号：

```bat
set EXE=.\SHIEP-Pipeline.exe
set SERVER=https://vpn.shiep.edu.cn

start "VPN-1" %EXE% --server %SERVER% --username 账号1 --password 密码1 --bind 127.0.0.1:1081 --fallback socks5h://127.0.0.1:10808
start "VPN-2" %EXE% --server %SERVER% --username 账号2 --password 密码2 --bind 127.0.0.1:1082 --fallback socks5h://127.0.0.1:10808
start "VPN-3" %EXE% --server %SERVER% --username 账号3 --password 密码3 --bind 127.0.0.1:1083 --fallback socks5h://127.0.0.1:10808
start "VPN-4" %EXE% --server %SERVER% --username 账号4 --password 密码4 --bind 127.0.0.1:1084 --fallback socks5h://127.0.0.1:10808
```

然后更改后缀名为.bat,运行后等待所有终端显示 `[VPN] ✓ tunnel established`。

### 2. 运行扫描

```powershell
# 全部学期
python -m src.main -c config.yaml

# 指定学期
python -m src.main -c config.yaml -s 404
```

### 3. 查看结果

终端输出彩色报表，同时生成 `results.json`：

- **成绩**：按行显示科目信息，绩点为 0 的行标红
- **学分计划**：大类汇总（含"缺"字标黄），未完成的小类以红色缩进显示
- **Cookie**：显示 JSESSIONID 和 SERVERNAME

## 学期 ID

打开成绩查询页面，F12 → Network → 切换学期下拉框，观察请求中的 `semesterId` 参数。已知学期 ID：

| 学期 | ID |
|------|-----|
| 2025-2026 第二学期 | 404 |

## 项目结构

```
multi-ip-cookie-scanner/
├── src/
│   ├── __init__.py
│   ├── main.py            # CLI 入口，配置加载，学期参数
│   ├── scanner.py         # 登录、Cookie提取、成绩爬取、学分计划爬取
│   ├── proxy_manager.py   # 代理池管理
│   └── reporter.py        # Rich 彩色输出，不合格标红，JSON 导出
├── config.example.yaml
├── launch_vpns.bat
├── setup.bat
├── requirements.txt
├── .gitignore
└── README.md
```

## 注意事项
- 若出现验证码，需手动处理或接入 OCR
- 
## 技术栈
- Python 3.13 + asyncio
- Playwright（浏览器自动化）
- aiohttp 风格的异步并发
- Rich（终端彩色输出）
- SHIEP-Pipeline（Rust 实现的 EasyConnect VPN）
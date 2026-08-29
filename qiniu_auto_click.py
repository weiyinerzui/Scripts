#!/usr/bin/env python3
"""
qiniu_auto_click.py — 七牛云 AI 推广活动自动领取额度

页面: https://www.qiniu.com/ai/promotion/invite

原理:
  页面"立即领取"按钮背后是官方接口(经 web-api.qiniu.com 代理):
    GET  /api/proxy/ai-inference/inapi/v3/promotion/consumable/points  可领取额度(需登录)
    POST /api/proxy/ai-inference/inapi/v3/promotion/invitation/claim   领取 {type, reward_id}
  每次领取消耗 1 点 = 300 万 Token 融合资源包。

  已实测: 接口支持连续调用, 无 UI 上的冷却限制; 但高频请求会触发服务端
  限流(server-error / errcode 50006), 脚本内置指数退避自动重试。
  脚本流程: 打开页面(持久化登录态) -> 循环领取直到额度耗尽 -> 退出。

用法:
  python qiniu_auto_click.py                # 自动领取直到额度耗尽
  python qiniu_auto_click.py --delay 3      # 每次领取间隔 3 秒(默认 2)
  python qiniu_auto_click.py --max 10       # 最多领取 10 次(调试用)

  首次运行会打开浏览器, 手动登录一次即可; 登录态持久化在 ./qiniu_profile,
  之后运行无需再次登录。
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException

URL = "https://www.qiniu.com/ai/promotion/invite"
API_BASE = "https://web-api.qiniu.com/api/proxy/ai-inference/inapi"
USER_INFO_API = "https://web-api.qiniu.com/api/user/info"
PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qiniu_profile")

# 连续失败次数超过该值后放弃(额度耗尽/接口异常)
MAX_CONSECUTIVE_FAILS = 5
# 单次 fetch 在页面内的超时(秒)。活动高峰期服务端响应极慢:
# 实测 points 接口 20s、claim 接口 95s 才返回(页面也提示"当前人数参与过多"),
# 必须留足余量, 否则会在服务端返回前误判为超时
FETCH_TIMEOUT = 180


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def keep_awake() -> None:
    """防止系统休眠(仅 Windows 有效, 其他平台静默跳过)。"""
    try:
        import ctypes

        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except AttributeError:
        pass  # Linux/macOS 无此 API, 忽略
    except Exception as e:
        log(f"keep_awake 失败(不影响运行): {e}")


def create_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    # 独立用户目录: 登录一次后 cookie 持久化, 之后无需重复登录
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")

    try:
        try:
            # 优先使用 webdriver-manager(若已安装)
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager

            return webdriver.Chrome(
                service=Service(ChromeDriverManager().install()), options=options
            )
        except ImportError:
            # Selenium 4.6+ 自带 Selenium Manager, 会自动下载驱动
            return webdriver.Chrome(options=options)
    except Exception as e:
        log(f"启动 Chrome 失败: {e}")
        sys.exit(1)


# ---------------------------------------------------------------- 页面内 JS

# 在页面上下文中执行 async fetch 并把结果回传给 Python
# - 内置 FETCH_TIMEOUT 秒超时兜底: 即使页面即将跳转/刷新导致回调丢失,
#   也会先超时返回, 避免 execute_async_script 一直挂到脚本超时
JS_FETCH = """
const callback = arguments[arguments.length - 1];
const [method, url, body, timeoutMs] = arguments;
let done = false;
const finish = (v) => { if (!done) { done = true; callback(v); } };
const timer = setTimeout(() => finish({httpStatus: 0, error: 'fetch-timeout'}), timeoutMs);
(async () => {
  try {
    const resp = await fetch(url, {
      method: method,
      credentials: 'include',
      headers: body ? {'Content-Type': 'application/json'} : {},
      body: body || undefined,
    });
    let data = null;
    try { data = await resp.json(); } catch (e) { /* 非 JSON 响应 */ }
    finish({httpStatus: resp.status, data: data});
  } catch (e) {
    finish({httpStatus: 0, error: String(e)});
  } finally {
    clearTimeout(timer);
  }
})();
"""


def page_fetch(driver, method: str, url: str, body: dict | None = None) -> dict:
    """在页面上下文里发起 fetch(自动携带登录 cookie), 返回 {httpStatus, data}。

    页面跳转/刷新会导致回调永久丢失, 此时捕获 TimeoutException 返回错误,
    由调用方决定重试。
    """
    try:
        return driver.execute_async_script(
            JS_FETCH,
            method,
            url,
            json.dumps(body) if body else None,
            FETCH_TIMEOUT * 1000,
        ) or {}
    except TimeoutException:
        return {"httpStatus": 0, "error": "script-timeout"}


# ---------------------------------------------------------------- 业务逻辑


def is_logged_in(driver) -> bool:
    r = page_fetch(driver, "GET", USER_INFO_API)
    return r.get("httpStatus") == 200


def wait_for_login(driver, timeout: int = 300) -> None:
    """等待用户在浏览器中完成登录(最长 timeout 秒)。"""
    if is_logged_in(driver):
        log("检测到已登录(使用持久化的登录态)。")
        return

    log("当前未登录, 请在打开的浏览器窗口中登录七牛云账号...")
    driver.get(
        "https://sso.qiniu.com?client_id=K6a8OASEcABGpG8RywoRjyzF6PW73g2E"
        f"&redirect_url={URL}"
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(5)
        try:
            if driver.current_url.startswith("https://www.qiniu.com") and is_logged_in(driver):
                log("登录成功!")
                driver.get(URL)
                time.sleep(3)
                return
        except WebDriverException:
            pass  # 页面跳转瞬间 driver 可能短暂失联, 忽略
    log("等待登录超时, 继续尝试(未登录状态下无法领取)...")


def get_points(driver, retries: int = 3) -> dict | None:
    """获取当前可领取额度。返回 {points, total} 或 None(未登录/异常)。

    接口被限流(server-error)或页面跳转(script-timeout)时自动退避重试。
    """
    wait = 10
    for attempt in range(retries):
        pts = page_fetch(driver, "GET", f"{API_BASE}/v3/promotion/consumable/points")
        if pts.get("httpStatus") == 200 and pts.get("data", {}).get("status"):
            return pts["data"].get("data")

        err = (pts.get("data") or {}).get("error") or pts.get("error") or ""
        if pts.get("httpStatus") == 401:
            return None  # 未登录, 重试无意义
        if attempt < retries - 1:
            log(f"  获取额度失败({err or pts}), {wait}s 后重试 ({attempt + 1}/{retries})...")
            time.sleep(wait)
            wait *= 2
    return None


def claim_reward(driver) -> tuple[bool, str]:
    """调用官方 claim 接口领取一次(reward_id=0, consumable 类型)。

    返回 (ok, msg); ok=False 且 msg 为 'retry' 时表示临时性失败可重试。
    """
    r = page_fetch(
        driver,
        "POST",
        f"{API_BASE}/v3/promotion/invitation/claim",
        {"type": "consumable", "reward_id": 0},
    )
    data = r.get("data") or {}
    if r.get("httpStatus") == 200 and data.get("status"):
        return True, "领取成功"

    err = data.get("error")
    # 注意: 服务端实际返回 "point-not-enough"(单数, errcode 50004),
    # 与页面代码里的 "points-not-enough" 拼写不同, 两种都要识别
    if err in ("points-not-enough", "point-not-enough") or data.get("errcode") == 50004:
        return False, "额度已耗尽"
    if err in ("reward-already-claimed", "pack-already-claimed"):
        return False, "奖励已兑换过"
    # 临时性失败: 服务端限流(server-error/50006)、页面跳转、网络抖动 -> 可重试
    return False, "retry"


def run(driver, delay: float, max_claims: int | None) -> None:
    """循环领取直到额度耗尽。"""
    points = get_points(driver)
    if points is None:
        log("无法获取额度(未登录或接口异常), 退出。")
        return

    total_points = points.get("points", 0)
    log(f"当前可领取: {total_points} 点(每点 = 300 万 Token), 开始领取...")

    claimed = 0
    fails = 0
    backoff = 10  # 临时性失败后的退避秒数
    while True:
        if max_claims and claimed >= max_claims:
            log(f"已达到最大领取次数 {max_claims}, 停止。")
            break

        ok, msg = claim_reward(driver)
        if ok:
            claimed += 1
            fails = 0
            backoff = 10
            remaining = total_points - claimed
            log(f"  ✔ 第 {claimed} 次领取成功 (剩余约 {remaining} 点)")
        elif msg == "retry":
            fails += 1
            log(f"  ⚠ 临时失败(限流/网络), {backoff}s 后重试 (连续 {fails}/{MAX_CONSECUTIVE_FAILS})")
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)  # 指数退避, 上限 2 分钟
            if fails >= MAX_CONSECUTIVE_FAILS:
                log("连续临时失败次数过多, 停止。")
                break
            continue
        else:
            fails += 1
            log(f"  ✘ {msg} (连续失败 {fails}/{MAX_CONSECUTIVE_FAILS})")
            if msg == "额度已耗尽":
                log("额度已耗尽, 停止。")
                break
            if fails >= MAX_CONSECUTIVE_FAILS:
                log("连续失败次数过多, 停止。")
                break

        time.sleep(delay)

    log(f"完成! 共领取 {claimed} 次 = {claimed * 300} 万 Token。")


def main() -> None:
    parser = argparse.ArgumentParser(description="七牛云 AI 推广活动自动领取额度")
    parser.add_argument("--delay", type=float, default=2, help="每次领取间隔秒数(默认 2)")
    parser.add_argument("--max", type=int, default=None, help="最多领取次数(默认不限)")
    args = parser.parse_args()

    keep_awake()
    driver = create_driver()
    # 脚本超时必须大于页面内 fetch 超时(FETCH_TIMEOUT), 否则 execute_async_script
    # 会先于页面内兜底超时抛 TimeoutException
    driver.set_script_timeout(FETCH_TIMEOUT + 60)

    try:
        driver.get(URL)
        time.sleep(3)
        wait_for_login(driver)

        run(driver, args.delay, args.max)

    except KeyboardInterrupt:
        log("收到中断, 退出。")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

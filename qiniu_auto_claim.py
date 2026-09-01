#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七牛云 AI 推广活动 - 自动领取 Token 奖励脚本
================================================
使用 Playwright 驱动独立的 Chromium 浏览器窗口，自动循环点击"立即领取"。

使用方法：
  1. 安装依赖：
       pip install playwright
       playwright install chromium
  2. 运行脚本：
       python qiniu_auto_claim.py
  3. 首次运行会打开浏览器窗口，请手动登录七牛云账号
  4. 登录后脚本会自动开始循环领取
  5. 按 Ctrl+C 停止脚本

脚本打开的是独立浏览器窗口，不影响你日常使用其他程序。
登录状态会被持久化保存，下次运行无需再次登录。
"""

import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("未安装 playwright，请先执行：")
    print("  pip install playwright")
    print("  playwright install chromium")
    sys.exit(1)

# ==================== 配置区 ====================

TARGET_URL = "https://www.qiniu.com/ai/promotion/invite"

# 浏览器用户数据目录（持久化登录状态，改路径可隔离多账号）
USER_DATA_DIR = str(Path.home() / ".qiniu_auto_claim_profile")

# "立即领取"按钮候选文字（按优先级排列，命中任意一个即点击）
CLAIM_BUTTON_TEXTS = ["立即领取", "领取奖励", "一键领取", "领取"]

# 成功弹框关闭按钮候选文字
POPUP_CLOSE_TEXTS = [
    "确定", "知道了", "好的", "确认", "完成",
    "我知道了", "关闭", "OK", "ok", "Close",
]

# 各阶段超时（秒）
WAIT_LOGIN_CHECK_INTERVAL = 5       # 检测登录状态的间隔
WAIT_POPUP_TIMEOUT = 30             # 点击领取后等待弹框出现的最长时间
WAIT_POPUP_CLOSE_TIMEOUT = 10       # 等待弹框关闭的最长时间
WAIT_REFRESH_TIMEOUT = 30           # 等待页面刷新的最长时间
POLL_INTERVAL = 2                  # 两次领取循环之间的间隔

# 点击后给页面响应的缓冲时间
POST_CLICK_DELAY = 1.5

# 是否打印调试 DOM 信息（遇到问题时打开）
DEBUG = False

# ==================== 配置区结束 ====================

# ------------------- 日志 -------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            Path.home() / "qiniu_auto_claim.log",
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("qiniu")


# ------------------- 运行状态 -------------------

_running = True


def _stop(signum=None, frame=None):
    global _running
    _running = False
    log.info("收到停止信号，脚本将在当前循环结束后退出…")


signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)


# ------------------- 工具函数 -------------------

def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


def find_claim_button(page):
    """在页面上查找"立即领取"按钮，返回 Locator 或 None。"""
    for text in CLAIM_BUTTON_TEXTS:
        # 优先匹配 button 元素
        loc = page.locator(f"button:has-text(\"{text}\")")
        cnt = loc.count()
        if cnt > 0:
            # 取第一个可见的
            for i in range(cnt):
                el = loc.nth(i)
                if el.is_visible():
                    if DEBUG:
                        log.debug(f"命中按钮[{text}] (button, index={i})")
                    return el
        # 其次匹配所有可点击元素
        loc = page.locator(f"[role='button']:has-text(\"{text}\"), a:has-text(\"{text}\")")
        cnt = loc.count()
        if cnt > 0:
            for i in range(cnt):
                el = loc.nth(i)
                if el.is_visible():
                    if DEBUG:
                        log.debug(f"命中按钮[{text}] (clickable, index={i})")
                    return el
    return None


def find_popup_close_button(page):
    """查找成功弹框的关闭按钮。"""
    # 策略1：按文字找按钮
    for text in POPUP_CLOSE_TEXTS:
        loc = page.locator(f"button:has-text(\"{text}\")")
        cnt = loc.count()
        if cnt > 0:
            for i in range(cnt):
                el = loc.nth(i)
                if el.is_visible():
                    return el
    # 策略2：找弹框内的关闭图标（X / close 类名）
    close_selectors = [
        ".el-dialog__close",           # Element UI
        ".ant-modal-close",            # Ant Design
        ".modal-close",
        "[class*='close'][role='button']",
        "[aria-label='Close']",
        "[aria-label='close']",
        ".icon-close",
        "button[class*='close']",
    ]
    for sel in close_selectors:
        loc = page.locator(sel)
        cnt = loc.count()
        if cnt > 0:
            for i in range(cnt):
                el = loc.nth(i)
                if el.is_visible():
                    return el
    return None


def wait_for_login(page):
    """等待用户登录完成。检测标志：页面上出现"立即领取"类按钮。"""
    log.info("=" * 60)
    log.info("请在打开的浏览器窗口中登录七牛云账号")
    log.info("登录完成后脚本会自动检测并开始领取")
    log.info("=" * 60)
    while _running:
        try:
            btn = find_claim_button(page)
            if btn is not None:
                # 二次确认：按钮可点击（非 disabled）
                if btn.is_enabled():
                    log.info("✅ 检测到登录状态，开始自动领取")
                    return True
        except Exception:
            pass
        time.sleep(WAIT_LOGIN_CHECK_INTERVAL)
    return False


def do_one_claim(page) -> bool:
    """执行一次领取流程，返回 True 表示成功完成一轮。"""
    # 1. 找领取按钮
    btn = find_claim_button(page)
    if btn is None:
        log.debug(f"[{now_str()}] 未找到领取按钮，可能正在刷新或无奖励可领")
        return False

    # 2. 点击
    try:
        btn.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    try:
        btn.click(timeout=5000)
        log.info(f"[{now_str()}] 已点击「立即领取」")
    except PWTimeout:
        log.warning("点击按钮超时，可能已被遮挡")
        return False
    except Exception as e:
        log.warning(f"点击按钮异常: {e}")
        return False

    # 3. 等待成功弹框出现
    popup_btn = None
    deadline = time.time() + WAIT_POPUP_TIMEOUT
    while time.time() < deadline and _running:
        try:
            popup_btn = find_popup_close_button(page)
            if popup_btn is not None:
                break
        except Exception:
            pass
        time.sleep(0.5)

    if popup_btn is None:
        # 可能弹框样式特殊，尝试按 Escape 或直接等刷新
        log.warning("未定位到弹框关闭按钮，尝试按 Escape 关闭")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        time.sleep(1)
        return True  # 仍认为完成一轮，继续循环

    # 4. 关闭弹框
    try:
        popup_btn.click(timeout=5000)
        log.info(f"[{now_str()}] 已关闭成功提示弹框")
    except Exception as e:
        log.warning(f"点击关闭按钮异常: {e}，尝试 Escape")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

    # 5. 等待弹框消失 + 页面刷新
    try:
        popup_btn.wait_for(state="detached", timeout=WAIT_POPUP_CLOSE_TIMEOUT * 1000)
    except Exception:
        pass

    # 6. 等待页面刷新完成（检测按钮重新出现或页面稳定）
    refresh_deadline = time.time() + WAIT_REFRESH_TIMEOUT
    while time.time() < refresh_deadline and _running:
        try:
            # 页面可能正在刷新，等 loading 结束
            ready = page.evaluate("document.readyState")
            if ready == "complete":
                # 再确认按钮重新出现
                if find_claim_button(page) is not None:
                    time.sleep(POST_CLICK_DELAY)
                    return True
        except Exception:
            # 页面正在刷新，JS 上下文失效，正常现象
            pass
        time.sleep(0.8)

    log.info("页面刷新等待超时，继续下一轮尝试")
    return True


# ------------------- 主流程 -------------------

def main():
    log.info("=" * 60)
    log.info("七牛云 AI 自动领取 Token 脚本启动")
    log.info(f"目标页面: {TARGET_URL}")
    log.info(f"用户数据目录: {USER_DATA_DIR}")
    log.info("=" * 60)

    with sync_playwright() as p:
        # 启动持久化浏览器上下文
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR,
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-default-browser-check",
                ],
            )
        except Exception as e:
            log.error(f"启动浏览器失败: {e}")
            log.error("请确认已执行: playwright install chromium")
            return

        page = context.pages[0] if context.pages else context.new_page()

        # 导航到目标页面
        log.info("正在打开活动页面…")
        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.warning(f"打开页面异常（可能网络慢）: {e}")

        # 等待登录
        if not wait_for_login(page):
            log.info("脚本被中断，退出")
            context.close()
            return

        # 主循环
        round_count = 0
        log.info("-" * 60)
        log.info("开始自动领取循环（Ctrl+C 停止）")
        log.info("-" * 60)

        while _running:
            try:
                ok = do_one_claim(page)
                if ok:
                    round_count += 1
                    if round_count % 10 == 0:
                        log.info(f"📊 已完成 {round_count} 轮领取")
                else:
                    # 没有按钮时短暂等待
                    time.sleep(POLL_INTERVAL)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"循环异常: {e}", exc_info=DEBUG)
                # 异常后等待，避免疯狂重试
                time.sleep(POLL_INTERVAL * 2)
                # 如果页面崩了，尝试重新打开
                try:
                    if page.is_closed():
                        page = context.new_page()
                        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(3)
                except Exception:
                    pass

        log.info(f"脚本停止，本轮共完成 {round_count} 次领取")
        try:
            context.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

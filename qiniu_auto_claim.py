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

# 成功弹框中的提示文字
SUCCESS_POPUP_TEXTS = ["领取成功"]
SUCCESS_POPUP_CONTAINERS = [
    "[role='dialog']",
    "[aria-modal='true']",
    ".el-dialog",
    ".el-dialog__wrapper",
    ".ant-modal",
    ".ant-modal-wrap",
    ".modal",
    ".modal-dialog",
    "[class*='dialog']",
    "[class*='modal']",
]

# 各阶段超时（秒）
WAIT_LOGIN_CHECK_INTERVAL = 5       # 检测登录状态的间隔
POLL_INTERVAL = 5                   # 两次领取循环之间的间隔（按钮迟迟不出现时）

# 单次点击「立即领取」的超时（注意：Playwright 的 timeout 单位是毫秒）
# 超时后会立即改用 JS 直接触发 click 绕过遮挡，所以这里给 6 秒即可
CLICK_TIMEOUT_MS = 6000

# 点击后给页面响应的缓冲时间
POST_CLICK_DELAY = 3.0

# 领取成功后等待网页自动刷新的时间（日志显示刷新远比 6s 慢）
POST_CLAIM_REFRESH_WAIT = 15.0

# 本轮没找到领取按钮时，继续等它重新出现的最长时间
BUTTON_REAPPEAR_WAIT = 10.0

# 强制刷新后的等待：先至少等 RELOAD_MIN_WAIT，再等按钮出现（最多 RELOAD_READY_TIMEOUT），
# 按钮出现后再等 RELOAD_SETTLE_WAIT 让页面稳定 —— 刷新后必须重新等待，频繁刷新没用
RELOAD_MIN_WAIT = 15.0
RELOAD_READY_TIMEOUT = 30.0
RELOAD_SETTLE_WAIT = 3.0

# 连续刷新的退避：第 1 次 15s、第 2 次 30s、第 3 次 60s，之后封顶 60s
RELOAD_BACKOFF_BASE = 15.0
RELOAD_BACKOFF_MAX = 60.0

# 连续弹框关闭失败多少次后强制刷新页面
MAX_CONSECUTIVE_POPUP_FAILURES = 3

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


def find_popup_close_button(page, container=None):
    """查找成功弹框的关闭按钮。"""
    root = container or page
    # 策略1：按文字找按钮
    for text in POPUP_CLOSE_TEXTS:
        loc = root.locator(f"button:has-text(\"{text}\")")
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
        loc = root.locator(sel)
        cnt = loc.count()
        if cnt > 0:
            for i in range(cnt):
                el = loc.nth(i)
                if el.is_visible():
                    return el
    return None


def find_success_popup_container(page):
    """查找包含成功文案的可见弹框容器。"""
    for text in SUCCESS_POPUP_TEXTS:
        for selector in SUCCESS_POPUP_CONTAINERS:
            loc = page.locator(selector).filter(has_text=text)
            for i in range(loc.count()):
                if loc.nth(i).is_visible():
                    return loc.nth(i)
    return None


def _find_any_visible_overlay(page):
    """查找页面上任何可见的遮罩/弹框容器（不依赖文字匹配）。"""
    overlay_selectors = [
        "[role='dialog']",
        "[aria-modal='true']",
        ".el-dialog__wrapper",
        ".el-dialog",
        ".ant-modal-wrap",
        ".ant-modal",
        ".modal-dialog",
        ".modal",
        "[class*='dialog']",
        "[class*='modal']",
        "[class*='overlay']",
        "[class*='mask']",
        "[class*='popup']",
        "[class*='toast']",
        "[class*='notification']",
        ".el-message-box__wrapper",
        ".el-message-box",
    ]
    for selector in overlay_selectors:
        loc = page.locator(selector)
        for i in range(loc.count()):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    return el
            except Exception:
                pass
    return None


def is_success_popup_visible(page) -> bool:
    """判断成功弹框是否仍在页面上。"""
    return find_success_popup_container(page) is not None


def _dump_popup_dom(page):
    """调试用：打印可能弹框的 HTML 结构。"""
    overlay = _find_any_visible_overlay(page)
    if overlay is not None:
        try:
            html = overlay.inner_html()
            log.info(f"[DEBUG] 弹框 HTML (前2000字符):\n{html[:2000]}")
        except Exception as e:
            log.info(f"[DEBUG] 无法获取弹框 HTML: {e}")
    else:
        # 最后手段：打印 body 下所有可见的顶层元素
        try:
            visible_divs = page.locator(
                "body > div:visible, body > [class*='overlay']:visible, "
                "body > [class*='modal']:visible, body > [class*='dialog']:visible"
            )
            for i in range(min(visible_divs.count(), 5)):
                try:
                    el = visible_divs.nth(i)
                    tag = el.evaluate("el => el.tagName")
                    cls = el.get_attribute("class") or ""
                    txt = el.inner_text()[:200]
                    log.info(f"[DEBUG] 可见顶层元素 #{i}: <{tag}> class='{cls}' text='{txt}'")
                except Exception:
                    pass
        except Exception as e:
            log.info(f"[DEBUG] 扫描可见元素失败: {e}")


def _click_any_button_in_overlay(page, overlay):
    """尝试点击弹框内任意 button / 可点击元素（兜底策略）。"""
    # 策略 A：找弹框内所有可见按钮，优先点最后一个（通常是"确定/关闭"）
    buttons = overlay.locator("button:visible")
    cnt = buttons.count()
    if cnt > 0:
        for i in range(cnt - 1, -1, -1):  # 倒序：最后的按钮通常是确认
            try:
                btn = buttons.nth(i)
                txt = btn.inner_text().strip()
                btn.click(timeout=3000)
                log.info(f"已点击弹框内按钮: '{txt[:20]}'")
                time.sleep(0.5)
                return True
            except Exception:
                pass

    # 策略 B：点击弹框内任意可见的可点击元素
    clickables = overlay.locator("a:visible, [role='button']:visible, .btn:visible")
    for i in range(clickables.count()):
        try:
            clickables.nth(i).click(timeout=3000)
            time.sleep(0.5)
            return True
        except Exception:
            pass

    # 策略 C：在弹框外点击（关闭遮罩层）
    try:
        page.mouse.click(10, 10)  # 左上角，大概率在弹框外
        time.sleep(0.5)
        return True
    except Exception:
        pass

    return False


def dismiss_success_popup(page) -> bool:
    """关闭成功弹框，返回弹框是否已消失。运用多层策略强制关闭。"""
    if not is_success_popup_visible(page):
        return True  # 已消失，视为成功

    if DEBUG:
        _dump_popup_dom(page)

    # ---- 第 1 层：Escape 键 ----
    try:
        page.keyboard.press("Escape")
        time.sleep(0.3)
    except Exception:
        pass
    if not is_success_popup_visible(page):
        return True

    # ---- 第 2 层：弹框内关闭按钮 ----
    popup = find_success_popup_container(page)
    if popup is not None:
        try:
            close_button = find_popup_close_button(page, popup)
            if close_button is not None:
                close_button.click(timeout=5000)
                time.sleep(0.5)
        except Exception:
            pass
    if not is_success_popup_visible(page):
        return True

    # ---- 第 3 层：按 Enter（很多弹框默认聚焦确认按钮） ----
    try:
        page.keyboard.press("Enter")
        time.sleep(0.3)
    except Exception:
        pass
    if not is_success_popup_visible(page):
        return True

    # ---- 第 4 层：弹框内任意可见按钮（兜底点击） ----
    overlay = find_success_popup_container(page) or _find_any_visible_overlay(page)
    if overlay is not None:
        _click_any_button_in_overlay(page, overlay)
    if not is_success_popup_visible(page):
        return True

    # ---- 第 5 层：再次 Escape + Enter 组合 ----
    try:
        page.keyboard.press("Escape")
        time.sleep(0.2)
        page.keyboard.press("Enter")
        time.sleep(0.3)
    except Exception:
        pass
    if not is_success_popup_visible(page):
        return True

    # ---- 第 6 层：wider overlay 扫描 + 按钮点击 ----
    wider_overlay = _find_any_visible_overlay(page)
    if wider_overlay is not None and wider_overlay != overlay:
        _click_any_button_in_overlay(page, wider_overlay)
    if not is_success_popup_visible(page):
        return True

    # ---- 结果 ----
    still_visible = is_success_popup_visible(page)
    if still_visible and DEBUG:
        log.warning("所有关闭策略均失败，弹出 DOM：")
        _dump_popup_dom(page)

    return not still_visible


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


def wait_for_claim_button(page, timeout=BUTTON_REAPPEAR_WAIT, poll_interval=1.0):
    """在 timeout 秒内轮询等待领取按钮重新出现且可点击，返回按钮或 None。"""
    deadline = time.monotonic() + timeout
    while _running and time.monotonic() < deadline:
        try:
            btn = find_claim_button(page)
            if btn is not None and btn.is_enabled():
                return btn
        except Exception:
            pass
        time.sleep(poll_interval)
    return None


def wait_for_page_ready(page, min_wait=RELOAD_MIN_WAIT) -> bool:
    """刷新后等待页面就绪：先至少等 min_wait 秒，再等按钮出现，最后再稳定一会。

    刷新不等于页面就绪，每次都必须重新走一遍等待，单纯频繁刷新解决不了问题。
    """
    # 第 1 段：固定等待，给页面重新加载的时间
    time.sleep(min_wait)
    if not _running:
        return False
    # 第 2 段：轮询等领取按钮出现（页面可能还在拉数据）
    btn = wait_for_claim_button(page, timeout=RELOAD_READY_TIMEOUT)
    if btn is None:
        log.warning(f"刷新后 {min_wait + RELOAD_READY_TIMEOUT:.0f}s 内未出现领取按钮，页面可能仍在加载")
        return False
    # 第 3 段：按钮已出现，再等一会让页面状态稳定，避免点上去又超时
    time.sleep(RELOAD_SETTLE_WAIT)
    log.info(f"页面已就绪（等待了约 {min_wait:.0f}s+），继续领取")
    return True


def _js_click(btn) -> bool:
    """JS 兜底点击：直接触发元素的 click()，绕过遮挡层对鼠标事件的拦截。

    领取成功后页面常留有不可见的容器层，Playwright 会一直等不到"能接收
    鼠标事件"而超时；DOM 层面的 click() 不受遮挡影响。
    """
    try:
        btn.evaluate("el => el.click()")
        return True
    except Exception as e:
        log.warning(f"JS 兜底点击失败: {e}")
        return False


def do_one_claim(page, consecutive_failures=0, refresh_count=0):
    """执行一次领取流程，返回 (ok, refreshed)。

    ok         : 本轮完成了领取点击，或已完成强制刷新
    refreshed  : 本轮实际执行了强制刷新（调用方据此累计退避时间）

    关键洞察：七牛云的成功弹框是 toast 通知（非阻塞模态框），
    会在几秒后自动消失，且不阻止底层按钮的点击。
    因此脚本只做"尽力关闭"，不将弹框关闭失败视为阻塞。
    """
    # ---- 优先：连续失败过多时强制刷新（放在最前面，避免被弹框检查阻断） ----
    if consecutive_failures >= MAX_CONSECUTIVE_POPUP_FAILURES:
        backoff = min(RELOAD_BACKOFF_BASE * (2 ** refresh_count), RELOAD_BACKOFF_MAX)
        log.warning(
            f"连续 {consecutive_failures} 次失败，强制刷新页面"
            f"（第 {refresh_count + 1} 次刷新，刷新后至少等 {backoff:.0f}s）"
        )
        try:
            page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.warning(f"页面刷新失败: {e}")
        # 刷新后必须重新等待页面就绪，退避时间随刷新次数递增，避免反复空刷
        wait_for_page_ready(page, min_wait=backoff)
        return True, True

    # ---- 前置：尽力关闭遗留弹框（不阻塞） ----
    try:
        if is_success_popup_visible(page):
            dismissed = dismiss_success_popup(page)
            if dismissed:
                log.debug("已关闭遗留的成功提示弹框")
            else:
                log.debug("遗留弹框未能关闭，但不阻塞后续流程")
            # 短暂等待让 DOM 稳定，但继续执行（toast 不阻挡按钮）
            time.sleep(0.5)
    except Exception:
        pass

    # 1. 找领取按钮（上一次领取后页面可能正在自动刷新，给时间等它重新出现）
    btn = find_claim_button(page)
    if btn is None:
        log.debug(f"[{now_str()}] 未找到领取按钮，等待 {BUTTON_REAPPEAR_WAIT:.0f}s 让页面刷新…")
        btn = wait_for_claim_button(page, timeout=BUTTON_REAPPEAR_WAIT)
    if btn is None:
        log.debug(f"[{now_str()}] 等待后仍无领取按钮，可能正在刷新或无奖励可领")
        return False, False

    # 2. 点击
    try:
        btn.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    try:
        btn.click(timeout=CLICK_TIMEOUT_MS)
        log.info(f"[{now_str()}] 已点击「立即领取」")
    except PWTimeout:
        # 普通点击被遮挡层拦住 → 改用 JS 直接触发，避免每次都白白超时+刷新
        if _js_click(btn):
            log.info(f"[{now_str()}] 普通点击超时，已用 JS 方式点击「立即领取」")
        else:
            log.warning("点击按钮超时，且 JS 兜底点击失败")
            return False, False
    except Exception as e:
        log.warning(f"点击按钮异常: {e}")
        return False, False

    # 3. 等待 toast 出现，尽力关闭（不阻塞）
    time.sleep(POST_CLICK_DELAY)
    try:
        if is_success_popup_visible(page):
            dismiss_success_popup(page)
    except Exception:
        pass

    # 4. 等待网页自动刷新（日志显示页面反应慢，给足缓冲后再进入下一轮）
    log.debug(f"[{now_str()}] 等待页面自动刷新 {POST_CLAIM_REFRESH_WAIT}s…")
    time.sleep(POST_CLAIM_REFRESH_WAIT)
    return True, False


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
        consecutive_failures = 0
        refresh_count = 0          # 连续强制刷新次数（用于退避，越刷等越久）
        log.info("-" * 60)
        log.info("开始自动领取循环（Ctrl+C 停止）")
        log.info("-" * 60)

        while _running:
            try:
                ok, refreshed = do_one_claim(page, consecutive_failures, refresh_count)
                if refreshed:
                    # 刷新不算领取成功：refresh_count 累加使下次刷新退避更久
                    refresh_count += 1
                    consecutive_failures = 0
                    continue
                if ok:
                    round_count += 1
                    consecutive_failures = 0  # 成功时重置
                    refresh_count = 0         # 页面恢复正常，重置刷新退避
                    if round_count % 10 == 0:
                        log.info(f"📊 已完成 {round_count} 轮领取")
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= MAX_CONSECUTIVE_POPUP_FAILURES:
                        log.warning(
                            f"⚠️ 连续 {consecutive_failures} 次失败，"
                            f"将在下一轮强制刷新页面并重新等待"
                        )
                    # 没有按钮时短暂等待
                    time.sleep(POLL_INTERVAL)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"循环异常: {e}", exc_info=DEBUG)
                # 异常后等待，避免疯狂重试
                time.sleep(POLL_INTERVAL * 2)
                # 如果页面崩了，尝试重新打开；整个浏览器都关了就正常退出
                try:
                    if context.is_closed():
                        log.error("浏览器上下文已关闭，退出主循环")
                        break
                    if page.is_closed():
                        page = context.new_page()
                        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
                        wait_for_page_ready(page, min_wait=RELOAD_MIN_WAIT)
                except Exception:
                    pass

        log.info(f"脚本停止，本轮共完成 {round_count} 次领取")
        try:
            context.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

# qiniu_auto_click.py
import time
import ctypes
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# 防止系统休眠（和原脚本等效）
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040
# 原脚本使用的值 0x80000003 = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | (低位位组合)
ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)

url = "https://www.qiniu.com/ai/promotion/invite"

# 创建 Chrome 浏览器（可添加更多 options 如需无头运行）
options = webdriver.ChromeOptions()
# options.add_argument("--headless=new")  # 需要可视化则注释掉
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

try:
    driver.get(url)

    print("请在浏览器中登录七牛云账号（如果需要），等待页面加载...")

    # 等待页面上出现目标按钮（最长等待 300s，给用户足够时间登录）
    WebDriverWait(driver, 300).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".icecream-btn-primary"))
    )

    # 注入 JS：每秒检查并点击目标按钮（与原脚本逻辑一致）
    js = r"""
    (function(){
      function autoClickButton() {
        const buttons = document.querySelectorAll('button.icecream-btn.icecream-btn-primary.icecream-btn-primary-large');
        let found = false;
        for (let btn of buttons) {
          if (btn.textContent.includes('继续邀请好友') || btn.textContent.includes('立即领取')) {
            try { btn.click(); } catch(e) { console.log('click error', e); }
            console.log('已点击按钮:', btn.textContent.trim());
            found = true;
            break;
          }
        }
        if (!found) {
          const fallbackBtn = document.querySelector('.icecream-btn-primary');
          if (fallbackBtn) {
            try { fallbackBtn.click(); } catch(e) { console.log('fallback click error', e); }
            console.log('已点击备用按钮 .icecream-btn-primary');
          } else {
            console.log('未找到任何可点击的按钮');
          }
        }
      }
      // 如果之前已设置 interval，则先清除（防止重复注入）
      if (window.__qiniuClickInterval) { clearInterval(window.__qiniuClickInterval); }
      window.__qiniuClickInterval = setInterval(autoClickButton, 1000);
    })();
    """
    driver.execute_script(js)

    print("已注入自动点击脚本。按 Ctrl+C 停止并退出。")

    # 保持运行，直到用户中断
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("收到中断，退出并清理...")
finally:
    try:
        # 清除页面中设置的 interval
        driver.execute_script("if(window.__qiniuClickInterval){ clearInterval(window.__qiniuClickInterval); }")
    except Exception:
        pass
    driver.quit()

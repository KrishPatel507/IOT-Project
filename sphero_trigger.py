from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def click_start_on_sphero():
    opts = Options()
    opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    driver = webdriver.Edge(options=opts)
    wait = WebDriverWait(driver, 10)

    # Find the Sphero Edu tab
    found_tab = False
    for handle in driver.window_handles:
        driver.switch_to.window(handle)
        url = driver.current_url.lower()
        if "edu.sphero.com" in url:
            found_tab = True
            break

    if not found_tab:
        print("[SPHERO] Could not find edu.sphero.com tab.")
        driver.quit()
        return

    # Try a few possible Start/Run buttons
    possible_xpaths = [
        "//button[contains(., 'Start')]",
        "//button[contains(., 'Run')]",
        "//span[contains(., 'Start')]/ancestor::button",
        "//span[contains(., 'Run')]/ancestor::button",
        "//*[contains(text(), 'Start')]/ancestor::button",
        "//*[contains(text(), 'Run')]/ancestor::button",
    ]

    clicked = False
    for xpath in possible_xpaths:
        try:
            btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
            driver.execute_script("arguments[0].click();", btn)
            print("[SPHERO] Clicked Start/Run button.")
            clicked = True
            break
        except Exception:
            pass

    if not clicked:
        print("[SPHERO] Could not find a clickable Start/Run button.")

    driver.quit()


if __name__ == "__main__":
    click_start_on_sphero()
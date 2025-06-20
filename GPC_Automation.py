import os
from flask import Flask, render_template, request, jsonify
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import asyncio
import subprocess
import json
import sys
import traceback
import threading
from collections import deque
import time

# Ensure Playwright Chromium is installed only once
venv_bin = os.path.dirname(sys.executable)
playwright_exec = os.path.join(venv_bin, "playwright")

if not os.path.exists(os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")):
    subprocess.run([playwright_exec, "install", "chromium"], check=True)

STORAGE_PATH = os.path.join(os.getcwd(), "storage", "auth.json")
app = Flask(__name__)

# Global state for session status
session_status = {
    "valid": False,
    "message": "Session not initialized"
}

# Queue system
class AutomationQueue:
    def __init__(self):
        self.queue = deque()
        self.current_processing = None
        self.lock = threading.Lock()
        self.active = False

    def add_apps(self, app_names):
        with self.lock:
            timestamp = time.time()
            for app_name in app_names:
                self.queue.append({'app_name': app_name, 'timestamp': timestamp})
            return len(self.queue)

    def get_next_app(self):
        with self.lock:
            if self.queue:
                self.current_processing = self.queue.popleft()
                return self.current_processing
            return None

    def get_status(self):
        with self.lock:
            return {
                'current': self.current_processing,
                'queue_size': len(self.queue),
                'queue_list': list(self.queue),
                'active': self.active
            }

    def start_processing(self):
        with self.lock:
            self.active = True

    def stop_processing(self):
        with self.lock:
            self.active = False
            self.current_processing = None

automation_queue = AutomationQueue()
automation_status = {"running": False}
DEFAULT_TIMEOUT = 300000  # 5 minutes

async def check_session_validity(page):
    try:
        # Check if we're on a login page or session is expired
        await page.wait_for_selector('text=Sign in', timeout=5000)
        return False, "Session expired or not logged in"
    except:
        try:
            # Check if we're on the expected page
            await page.wait_for_selector("#main-content", timeout=5000)
            return True, "Session is valid"
        except:
            return False, "Unable to verify session status"

async def wait_for_login(page):
    print("🔐 Please log in manually...", flush=True)
    while True:
        try:
            await page.wait_for_selector('text=Dashboard', timeout=5000)
            break
        except:
            await asyncio.sleep(2)

async def wait_for_element(page, selector, timeout=DEFAULT_TIMEOUT, state="visible"):
    """Wait up to 5 minutes for element with enhanced visibility checks."""
    try:
        element = await page.wait_for_selector(selector, timeout=timeout, state=state)
        await element.scroll_into_view_if_needed()
        return element
    except PlaywrightTimeoutError:
        print(f"⏰ Timeout {timeout}ms waiting for element: {selector}", flush=True)
        raise
    except Exception as e:
        print(f"❌ Unexpected error waiting for element: {selector} - {str(e)}", flush=True)
        raise

async def goto_app_section_until_success(page, app_id, section):
    url = f"https://play.google.com/console/u/0/developers/8453266419614197800/app/{app_id}/app-content/{section}?source=dashboard"
    print(f"🌐 Navigating to {section} page...", flush=True)
    
    retries = 0
    while True:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)  # 60 sec timeout
            print(f"✅ Successfully navigated to {section}", flush=True)
            break
        except Exception as e:
            print(f"⚠️ Failed to navigate ({e}), retrying...", flush=True)
            retries += 1
            if "Page crashed" in str(e) or retries > 5:
                print("🔄 Refreshing page due to crash or too many retries...", flush=True)
                try:
                    await page.reload(wait_until="domcontentloaded")
                except:
                    pass  # Ignore reload errors
            await asyncio.sleep(2)

async def click_element(page, element, description=""):
    """Enhanced click with multiple fallback methods."""
    try:
        await element.click()
        print(f"✅ Clicked {description}", flush=True)
    except Exception:
        try:
            await element.dispatch_event('click')
            print(f"ℹ️ Used dispatch_event for {description}", flush=True)
        except Exception:
            try:
                await page.evaluate("el => el.click()", element)
                print(f"ℹ️ Used JS click for {description}", flush=True)
            except Exception:
                print(f"❌ Failed to click {description}", flush=True)
                raise

async def click_button_by_material_radio_debug_id(page, debug_id):
    selector = f"material-radio[debug-id='{debug_id}'] input[type='radio']"
    element = await wait_for_element(page, selector)
    await click_element(page, element, f"material-radio {debug_id}")

async def click_button_by_console_form_expandable_debug_id(page, debug_id):
    selector = f"console-form-expandable-section[debug-id='{debug_id}'] input[type='radio']"
    element = await wait_for_element(page, selector)
    await click_element(page, element, f"console-form-expandable {debug_id}")

async def click_button_by_material_radio_group_debug_id(page, debug_id, index=0):
    group_selector = f"material-radio-group[debug-id='{debug_id}']"
    try:
        group = await wait_for_element(page, group_selector)
        print(f"✅ Radio group container found: {debug_id}", flush=True)
    except Exception:
        print(f"❌ Failed to find radio group container: {debug_id}", flush=True)
        raise

    radio_selector = f"{group_selector} input[type='radio'], {group_selector} [role='radio']"
    try:
        await wait_for_element(page, radio_selector)
        radio_buttons = await page.query_selector_all(radio_selector)

        if len(radio_buttons) <= index:
            raise Exception(f"Only found {len(radio_buttons)} radio buttons (needed index {index})")

        target = radio_buttons[index]
        await click_element(page, target, f"radio button {index} in group {debug_id}")

    except Exception as e:
        found_count = len(await page.query_selector_all(radio_selector))
        print(f"  Found {found_count} radio buttons in group", flush=True)
        raise Exception(f"Failed to click radio button {index} in group '{debug_id}'") from e

async def click_button_ingroup_by_material_radio_group_debug_id(page, parent_debug_id, parent_index, debug_id, child_index, radio_button_index):
    try:
        parent_containers = await page.query_selector_all(f"console-block-1-column[debug-id='{parent_debug_id}']")
        if len(parent_containers) > parent_index:
            parent = parent_containers[parent_index]
            material_radio_groups = await parent.query_selector_all(f"material-radio-group[debug-id='{debug_id}']")

            async def click_radio(radio_button):
                await page.evaluate("(el) => el.scrollIntoView({behavior: 'smooth', block: 'center'})", radio_button)
                await page.evaluate("""
                    (checkbox) => {
                        ['click', 'mousedown', 'mouseup', 'mouseenter', 'mouseleave'].forEach(event => {
                            const evt = new MouseEvent(event, { bubbles: true, cancelable: true, view: window });
                            checkbox.dispatchEvent(evt);
                        });
                    }
                """, radio_button)

            if parent_index == 4 and len(material_radio_groups) == 5:
                for i, group in enumerate(material_radio_groups):
                    radio_buttons = await group.query_selector_all("input[type='radio']")
                    if len(radio_buttons) > radio_button_index:
                        await click_radio(radio_buttons[radio_button_index])
                        print(f"Radio button {radio_button_index + 1} clicked in parent index {parent_index}, group {i + 1}.", flush=True)
            else:
                if len(material_radio_groups) > child_index:
                    group = material_radio_groups[child_index]
                    radio_buttons = await group.query_selector_all("input[type='radio']")
                    if len(radio_buttons) > radio_button_index:
                        await click_radio(radio_buttons[radio_button_index])
                        print(f"Radio button {radio_button_index + 1} clicked in parent index {parent_index}, child index {child_index}.", flush=True)
    except Exception as e:
        print(f"Error while interacting: {e}", flush=True)

async def click_button_by_xpath(page, xpath):
    try:
        element = await wait_for_element(page, f'xpath={xpath}')
        await click_element(page, element, f"XPath {xpath}")
    except Exception:
        print(f"❌ XPath click failed: {xpath}", flush=True)
        raise

async def click_checkbox_by_debug_id(page, debug_id, index=0):
    try:
        container_selector = f"material-checkbox[debug-id='{debug_id}']"
        await wait_for_element(page, container_selector)

        checkboxes = await page.query_selector_all(container_selector)
        if index >= len(checkboxes):
            print(f"Invalid index {index}. Only {len(checkboxes)} checkboxes available.", flush=True)
            return

        container = checkboxes[index]
        await page.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })", container)
        checkbox = await container.query_selector("input[type='checkbox']")
        await click_element(page, checkbox, f"checkbox {debug_id}")
        print(f"Checkbox {index} clicked.", flush=True)
    except Exception as e:
        print(f"Checkbox click error: {e}", flush=True)
        raise

async def upload_csv_from_static_file(page, filename, timeout=30000):
    """
    Upload CSV file from static folder, retrying up to 5 times if upload confirmation fails.

    Args:
        page: Playwright page object
        filename: Name of file in static folder
        timeout: Maximum time to wait for file input (ms)
    """
    static_folder = os.path.join(os.getcwd(), 'static')
    file_path = os.path.join(static_folder, filename)

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found in static folder: {filename}")
    if not filename.lower().endswith('.csv'):
        print(f"⚠️ Warning: File '{filename}' may not be a CSV file")

    file_input_selector = "input[type='file']"
    
    try:
        file_input = await page.wait_for_selector(
            file_input_selector,
            state="attached",
            timeout=timeout
        )

        is_disabled = await file_input.get_attribute("disabled")
        if is_disabled:
            raise Exception("File input is disabled!")
    except Exception as e:
        raise Exception(f"File input not ready: {str(e)}")

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"📤 Upload attempt {attempt} for '{filename}'...")
            await file_input.set_input_files(file_path)
            
            # Wait to confirm upload (adjust selector if needed)
            await page.wait_for_selector(f"text='{filename}'", timeout=5000)
            print(f"✅ File '{filename}' uploaded and detected on page!")
            return  # Success, exit function
        
        except Exception as e:
            print(f"⚠️ Upload attempt {attempt} failed: {e}")
            if attempt == max_attempts:
                print(f"❌ Upload failed after {max_attempts} attempts for '{filename}'")
                raise Exception(f"Upload failed: {str(e)}")
            await asyncio.sleep(1)  # Wait before retrying

async def automate_play_console():
    global session_status
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--start-maximized"])

        if os.path.exists(STORAGE_PATH):
            print("✅ Found existing session, loading it...", flush=True)
            context = await browser.new_context(storage_state=STORAGE_PATH, no_viewport=True)
            page = await context.new_page()
            
            # Test if session is still valid
            await page.goto("https://play.google.com/console/u/0/developers/8453266419614197800/", wait_until="domcontentloaded")
            is_valid, message = await check_session_validity(page)
            
            if not is_valid:
                session_status = {"valid": False, "message": message}
                print(f"⚠️ Session is invalid: {message}", flush=True)
                await page.close()
                await context.close()
                automation_queue.stop_processing()
                automation_status["running"] = False
                return
            
            session_status = {"valid": True, "message": "Session is valid"}
            await page.close()
        else:
            print("🔓 No saved session, starting fresh...", flush=True)
            session_status = {"valid": False, "message": "No session found, please log in"}
            context = await browser.new_context(no_viewport=True)
            page = await context.new_page()
            await page.goto("https://play.google.com/console/u/0/developers/8453266419614197800/create-new-app", wait_until="domcontentloaded")
            await wait_for_login(page)
            await context.storage_state(path=STORAGE_PATH)
            session_status = {"valid": True, "message": "New session created"}
            await page.close()

        print("🚀 Automation worker ready to process queue...", flush=True)
        automation_queue.start_processing()
        automation_status["running"] = True

        while True:
            next_app = automation_queue.get_next_app()
            if not next_app:
                print("⏳ Queue is empty, waiting...", flush=True)
                await asyncio.sleep(5)
                continue

            app_name = next_app['app_name']
            page = await context.new_page()

            try:
                print(f"\n=== Processing app: {app_name} ===", flush=True)
                await page.goto("https://play.google.com/console/u/0/developers/8453266419614197800/create-new-app", wait_until="domcontentloaded")
                
                # Check session again in case it expired during processing
                is_valid, message = await check_session_validity(page)
                if not is_valid:
                    session_status = {"valid": False, "message": message}
                    print(f"⚠️ Session expired during processing: {message}", flush=True)
                    await page.close()
                    automation_queue.stop_processing()
                    automation_status["running"] = False
                    return
                
                await page.wait_for_selector("#main-content", state="visible", timeout=DEFAULT_TIMEOUT)

                input_xpath = '//*[@id="main-content"]/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/create-new-app-page/console-form/console-form-row[1]/div/div[2]/div[1]/material-input/label/input'
                input_field = await page.wait_for_selector(f'xpath={input_xpath}', timeout=DEFAULT_TIMEOUT)
                
                await input_field.fill("")
                await asyncio.sleep(0.5)
                await input_field.fill(app_name)
                await asyncio.sleep(0.5)

                print(f"✅ App name '{app_name}' entered successfully.", flush=True)

                await click_button_by_material_radio_debug_id(page, "app-radio")
                print("Radio button 'app-radio' clicked.", flush=True)

                await click_button_by_material_radio_debug_id(page, "free-radio")
                print("Radio button 'free-radio' clicked.", flush=True)

                # Check "guidelines-checkbox"
                await click_checkbox_by_debug_id(page, "guidelines-checkbox")

                # Check "export-laws-checkbox"
                await click_checkbox_by_debug_id(page, "export-laws-checkbox")

                # Create App button
                try:
                    async with page.expect_navigation(wait_until="load", timeout=300_000):
                        await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/create-new-app-page/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div/material-button[1]/button/div[2]")
                except Exception as e:
                    print("❌ An error occurred:", e, flush=True)
                    traceback.print_exc(file=sys.stdout)

                # 🌟 Get current URL and extract the app_id
                created_app_url = page.url
                print(f"🌐 Created app URL: {created_app_url}", flush=True)

                # Extract app_id from URL
                import re
                match = re.search(r'/app/([^/]+)/', created_app_url)
                if match:
                    app_id = match.group(1)
                    print(f"🆔 Extracted App ID: {app_id}", flush=True)

                # Privacy policy URL
                await goto_app_section_until_success(page, app_id, "privacy-policy")

                # Flipdish privacy policy URL
                input_xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-privacy-policy-page/div/console-block-1-column[2]/div/div/console-form/material-input/label/input"
                text_field = await wait_for_element(page, f'xpath={input_xpath}')
                await text_field.fill("https://www.flipdish.com/privacy-policy")     

                # Save button
                await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-privacy-policy-page/div/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span")
                await asyncio.sleep(15)

                # App access URL
                await goto_app_section_until_success(page, app_id, "testing-credentials")

                # Login required
                await click_button_by_console_form_expandable_debug_id(page, "login-required-expandable-section")

                # Add instructions
                await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-testing-credentials-page/console-block-1-column/div/div/console-form/console-form-expandable-section[2]/div/expandable-container/div/div/console-button-set/div/button/material-icon/i")

                # Instructions
                input_xpath = "//*[@id='default-acx-overlay-container']/div[2]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/console-block-1-column/div/div/console-form/console-form-row[1]/div/div[2]/div[1]/material-input/label/input"
                text_field = await wait_for_element(page, f'xpath={input_xpath}')
                await text_field.fill("For Testing")

                input_xpath = "//*[@id='default-acx-overlay-container']/div[2]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/console-block-1-column/div/div/console-form/div/console-form-row[1]/div/div[2]/div[1]/material-input/label/input"
                text_field = await wait_for_element(page, f'xpath={input_xpath}')
                await text_field.fill("+481234567890")

                input_xpath = "//*[@id='default-acx-overlay-container']/div[2]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/console-block-1-column/div/div/console-form/div/console-form-row[2]/div/div[2]/div[1]/material-input/label/input"
                text_field = await wait_for_element(page, f'xpath={input_xpath}')
                await text_field.fill("7890")

                input_xpath = "//*[@id='default-acx-overlay-container']/div[2]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/console-block-1-column/div/div/console-form/div/console-block-3-1/div[1]/div/div/console-form-row/div/div/div[1]/material-input/label/span[2]/textarea"
                text_field = await wait_for_element(page, f'xpath={input_xpath}')
                await text_field.fill("""Use the demo account and PIN provided for logging into the app. Login authentication in the app is based on the user's phone number. PLEASE BE SURE TO REMOVE INITIAL +1 PREFIX.

PLACING AN ORDER:

PLEASE DO NOT PLACE THE ORDER - THIS IS A REAL LIVE RESTAURANT

PAYMENT METHODS: screen has been designed to show information, it is not possible to modify, add or remove payment methods like Cash etc. This can only be done for payment cards. BANK CONTACT &IDEAL only for NL stores.""")

                print("Instructions entered successfully.", flush=True)

                # No additional information needed - Checkbox
                await click_checkbox_by_debug_id(page, "no-additional-details-required-checkbox")

                # Add
                await click_button_by_xpath(page, "//*[@id='default-acx-overlay-container']/div[2]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div/button[1]/span")

                # Save button
                await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-testing-credentials-page/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span")
                await asyncio.sleep(15)

                # Ads URL
                await goto_app_section_until_success(page, app_id, "ads-declaration")

                # No ads
                await click_button_by_material_radio_group_debug_id(page, "contains-ads-radio-group", index=1)

                # Save button
                await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-ads-declaration-page/div/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span")
                await asyncio.sleep(15)

                # Content ratings URL
                await goto_app_section_until_success(page, app_id, "content-rating-overview")

                # Start questionnaire
                try:
                    xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-rating-overview-page/console-page-header/console-block-1-column/div/div/partner-program-get-started/get-started/div/div[1]/div/console-button-set/div[1]/button/span"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the button: {e}")

                # Email address
                input_xpath = "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-rating-iarc-questionnaire-page/console-form/fill-questionnaire-flow/console-form/console-block-1-column/div/div/material-stepper/div[2]/div/app-category-step/console-section/div/div/console-block-1-column/div/div/console-form-row[1]/div/div[2]/div[1]/material-input/label/input"
                input_field = await wait_for_element(page, f'xpath={input_xpath}')
                await input_field.fill("help@flipdish.com")

                # Category
                await click_button_by_material_radio_group_debug_id(page, "app-category-radio-group", index=2)

                # IARC Checkbox
                await click_checkbox_by_debug_id(page, "iarc-tou-checkbox")

                # Next button
                try:
                    xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-rating-iarc-questionnaire-page/console-form/fill-questionnaire-flow/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item/button/span"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the button: {e}")

                # All other app types
                try:
                    parent_containers = await page.locator("console-block-1-column[debug-id='question-category-title']").all()
                    
                    for parent_index, parent_container in enumerate(parent_containers):
                        material_radio_groups = await parent_container.locator("material-radio-group[debug-id='single-response-radio-group']").all()
                        
                        if parent_index < 4:
                            if material_radio_groups:
                                await click_button_ingroup_by_material_radio_group_debug_id(
                                    page, "question-category-title", parent_index, "single-response-radio-group", 0, 1
                                )
                        else:
                            for i in range(5):
                                if len(material_radio_groups) > i:
                                    await click_button_ingroup_by_material_radio_group_debug_id(
                                        page, "question-category-title", parent_index, "single-response-radio-group", i, 1
                                    )
                except Exception as e:
                    print(f"Error clicking 'No' buttons: {e}")

                # Save button
                try:
                    xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-rating-iarc-questionnaire-page/console-form/fill-questionnaire-flow/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[3]/overflowable-item[1]/button/span"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the button: {e}")
                await asyncio.sleep(10)
                
                # Next button
                try:
                    xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-rating-iarc-questionnaire-page/console-form/fill-questionnaire-flow/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item/button/span"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the button: {e}")

                # Save button
                try:
                    xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-rating-iarc-questionnaire-page/console-form/fill-questionnaire-flow/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(15)           

                # Target audience and content URL
                await goto_app_section_until_success(page, app_id, "target-audience-content")

                # Target age button
                try:
                    await click_checkbox_by_debug_id(page, "age-band-checkboxes", index=5)
                except Exception as e:
                    print(f"Failed to click the checkbox: {e}")

                # Next button
                try:
                    xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-target-audience-content-page/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div/button[1]/span"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the button: {e}")

                # Save button
                try:
                    xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-target-audience-content-page/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the button: {e}")
                await asyncio.sleep(15)                                

                # Data safety URL
                await goto_app_section_until_success(page, app_id, "data-privacy-security")

                # Import button
                try:
                    xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-play-safety-labels-page/console-page-header/div/div/div/console-header/div/div/div[1]/div[2]/div/div/console-button-set/div/button[2]/span"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Upload file
                await upload_csv_from_static_file(page, "data_safety_export_Jan24.csv")

                # Import button
                try:
                    xpath = "//*[@id='default-acx-overlay-container']/div[3]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div/button[1]/span"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Import button
                try:
                    xpath = "//*[@id='default-acx-overlay-container']/div[4]/material-dialog/focus-trap/div[2]/div/footer/div/div/console-button-set/div/button[2]/span"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Next Buttons
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-play-safety-labels-page/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[1]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(5)

                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-play-safety-labels-page/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[1]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(5)

                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-play-safety-labels-page/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[1]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(5)

                # Save button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-play-safety-labels-page/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[3]/overflowable-item[3]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(15)

                # Government app URL
                await goto_app_section_until_success(page, app_id, "government-apps")

                # No government app button
                await click_button_by_material_radio_debug_id(page, "no-radio")
                print("Radio button 'no-radio' clicked.")

                # Save button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-government-apps-page/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(15)

                # Financial features URL
                await goto_app_section_until_success(page, app_id, "financial-features")

                # Financial features in your app
                try:
                    await click_checkbox_by_debug_id(page, "none-response")
                except Exception as e:
                    print(f"Failed to click the checkbox: {e}")

                # Next button
                try:
                    await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-finance-declaration-page/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[1]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Save button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-finance-declaration-page/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[3]/overflowable-item[3]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(15)

                # Health apps URL
                await goto_app_section_until_success(page, app_id, "health")

                # App features button
                try:
                    await click_checkbox_by_debug_id(page, "POLICY_RESPONSE_CHOICE_ID_NOT_HEALTH_APP")
                except Exception as e:
                    print(f"Failed to click the checkbox: {e}")

                # Save button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-health-page/policy-declaration/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(15)

                # Dashboard button
                try:                
                    async with page.expect_navigation(wait_until="load", timeout=300_000):
                        await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-health-page/console-page-header/div/div/div/console-button-set/div/a/material-icon/i")
                except Exception as e:
                    print("❌ An error occurred:", e, flush=True)
                    traceback.print_exc(file=sys.stdout)

                # Store settings button
                try:                
                    async with page.expect_navigation(wait_until="load", timeout=300_000):
                        await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/expandable-container/div/div/div/div/task-group[2]/div[2]/div/task[1]/div/div[2]/div/material-icon/i")
                except Exception as e:
                    print("❌ An error occurred:", e, flush=True)
                    traceback.print_exc(file=sys.stdout)

                # Edit button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/store-settings-page/console-form/console-section[1]/div/console-header/div/div/div[1]/div[2]/div/console-button-set/div/material-button/button/div[2]")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # App category button
                try:
                    await click_button_by_xpath(page, "/html/body/div[2]/div[3]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/console-block-1-column/div/div/console-form-row[2]/div/div[2]/div[1]/material-dropdown-select/dropdown-button/div/material-icon/i")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Food & drink button
                try:
                    await click_button_by_xpath(page, "/html/body/div[2]/div[5]/div/div/div[2]/div[2]/material-list/div/div/material-select-dropdown-item[13]/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Save button
                try:
                    await click_button_by_xpath(page, "//*[@id='default-acx-overlay-container']/div[3]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(5)

                # Cross button
                try:
                    await click_button_by_xpath(page, "/html/body/div[2]/div[3]/div/focus-trap/div[2]/relative-popup/div/span/div/div[1]/div/button/i")
                except Exception as e:
                    print(f"Failed to click the button: {e}")

                # Manage tags button
                try:
                    await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/store-settings-page/console-form/console-section[1]/div/div/console-block-1-column/div/div/crispr/console-form-row/div/div[2]/div[1]/console-button-set/div/material-button")
                    print("Button clicked successfully.")
                except Exception as e:
                    print(f"Failed to click the button: {e}")

                try:
                    await click_button_by_xpath(page, "/html/body/div[2]/div[2]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/console-block-1-column[2]/div/div/console-table/div/div/ess-table/ess-particle-table/div[1]/div/div[2]/div[34]/console-table-tools-cell/div/mat-checkbox")
                    print("Checkbox clicked successfully.")
                except Exception as e:
                    print(f"Failed to click the checkbox: {e}")

                try:
                    await click_button_by_xpath(page, "/html/body/div[2]/div[2]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/console-block-1-column[2]/div/div/console-table/div/div/ess-table/ess-particle-table/div[1]/div/div[2]/div[46]/console-table-tools-cell/div/mat-checkbox")
                    print("Checkbox clicked successfully.")
                except Exception as e:
                    print(f"Failed to click the checkbox: {e}")

                try:
                    xpath = "/html/body/div[2]/div[2]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/console-block-1-column[2]/div/div/console-table/div/div/ess-table/ess-particle-table/div[1]/div/div[2]/div[47]/console-table-tools-cell/div/mat-checkbox"
                    await click_button_by_xpath(page, xpath)
                    print("Checkbox clicked successfully.")
                except Exception as e:
                    print(f"Failed to click the checkbox: {e}")

                try:
                    xpath = "/html/body/div[2]/div[2]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/console-block-1-column[2]/div/div/console-table/div/div/ess-table/ess-particle-table/div[1]/div/div[2]/div[69]/console-table-tools-cell/div/mat-checkbox"
                    await click_button_by_xpath(page, xpath)
                    print("Checkbox clicked successfully.")
                except Exception as e:
                    print(f"Failed to click the checkbox: {e}")

                try:
                    xpath = "/html/body/div[2]/div[2]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/console-block-1-column[2]/div/div/console-table/div/div/ess-table/ess-particle-table/div[1]/div/div[2]/div[115]/console-table-tools-cell/div/mat-checkbox"
                    await click_button_by_xpath(page, xpath)
                    print("Checkbox clicked successfully.")
                except Exception as e:
                    print(f"Failed to click the checkbox: {e}")

                # Apply button
                try:
                    xpath = "//*[@id='default-acx-overlay-container']/div[2]/div/focus-trap/div[2]/relative-popup/div/span/div/div[3]/div/console-button-set/div/button[2]/span"
                    await click_button_by_xpath(page, xpath)
                    print("Button clicked successfully.")
                except Exception as e:
                    print(f"Failed to click the button: {e}")

                # Edit button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/store-settings-page/console-form/console-section[2]/div/console-header/div/div/div[1]/div[2]/div/console-button-set/div/material-button/button/div[2]")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Fill email field
                input_xpath = "//*[@id='default-acx-overlay-container']/div[4]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/console-block-1-column/div/div/console-form-row[1]/div/div[2]/div[1]/material-input/label/input"
                input_field = await wait_for_element(page, f'xpath={input_xpath}')
                await input_field.fill("help@flipdish.com")

                # Save button
                try:
                    await click_button_by_xpath(page, "//*[@id='default-acx-overlay-container']/div[4]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(5)

                # Cross button
                try:
                    await click_button_by_xpath(page, "//*[@id='default-acx-overlay-container']/div[4]/div/focus-trap/div[2]/relative-popup/div/span/div/div[1]/div/button/i")
                except Exception as e:
                    print(f"Failed to click the button: {e}")                    

                # Store listings button
                try:
                    await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/material-drawer[2]/navigation/nav/div/div[6]/navigation-item/div/expandable-container/div/div/navigation-item[1]/div/expandable-container/div/div/navigation-item[1]/div/a/span")
                except Exception as e:
                    print(f"Failed to click the button: {e}")

                # Store listings button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/custom-store-listings-overview-page/console-block-1-column/div/div/partner-program-get-started/get-started/div/div[1]/div/console-button-set/div/button[1]/span")
                except Exception as e:
                    print(f"Failed to click the button: {e}")

                input_xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/main-store-listing-page/listing-localizations/localization-section/div/div[2]/localized-listing/console-block-1-column[3]/div/div/console-form/console-form-row[2]/div/div[2]/div[1]/localized-text-input/div/div/material-input/label/input"
                input_field = await wait_for_element(page, f'xpath={input_xpath}')
                await input_field.fill("Amazing food delivered to your door!")

                input_xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/main-store-listing-page/listing-localizations/localization-section/div/div[2]/localized-listing/console-block-1-column[3]/div/div/console-form/console-form-row[3]/div/div[2]/div[1]/localized-text-input/div/div/material-input/label/span[2]/textarea"
                input_field = await wait_for_element(page, f'xpath={input_xpath}')
                await input_field.fill(f"{app_name} is committed to providing the best food and drink experience in your own home. Order online here at {app_name} or order from our app!")

                # Save as draft button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/main-store-listing-page/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[3]/overflowable-item[1]/button/span")
                except Exception as e:
                    print(f"Failed to click the button: {e}")

                print(f"✅ App '{app_name}' processed and removed from queue.", flush=True)

            except PlaywrightTimeoutError as e:
                print(f"🔥 Timeout for '{app_name}': {e}", flush=True)
            except Exception as e:
                print(f"🔥 Error processing '{app_name}': {e}", flush=True)
                traceback.print_exc()
            finally:
                await page.close()
                automation_queue.current_processing = None

            await asyncio.sleep(10)

def start_automation():
    asyncio.run(automate_play_console())

worker_thread = threading.Thread(target=start_automation, daemon=True)
worker_thread.start()

# Flask routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health', methods=['GET'])
def health_check():
    return "Server is healthy!", 200

@app.route('/run_automation', methods=['POST'])
def run_automation():
    try:
        # Check session status before proceeding
        if not session_status.get("valid", False):
            return jsonify({
                "status": "error",
                "message": f"Cannot start automation: {session_status.get('message', 'Session not valid')}",
                "session_status": session_status
            })

        app_names_input = request.form.get("app_names")
        if app_names_input:
            app_names = [name.strip() for name in app_names_input.split("\n") if name.strip()]
            queue_size = automation_queue.add_apps(app_names)

            return jsonify({
                "status": "success",
                "message": f"Automation started! {len(app_names)} apps added to queue.",
                "queue_size": queue_size,
                "running": automation_status["running"],
                "session_status": session_status
            })

        return jsonify({"status": "error", "message": "No app names provided!"})
    except Exception as e:
        print(f"🔥 Crash in /run_automation: {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)})

@app.route('/automation_status', methods=['GET'])
def automation_status_check():
    status = automation_queue.get_status()
    return jsonify({
        "running": automation_status["running"],
        "current_processing": status['current'],
        "queue_size": status['queue_size'],
        "queue_list": status['queue_list'],
        "session_status": session_status
    })

@app.route('/session_status', methods=['GET'])
def get_session_status():
    return jsonify(session_status)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    app.run(host='0.0.0.0', port=port)
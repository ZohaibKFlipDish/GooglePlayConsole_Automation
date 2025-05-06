import os
from flask import Flask, render_template, request, jsonify
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import asyncio
from threading import Thread

app = Flask(__name__)

automation_status = {"running": False}

def run_automation_in_thread(app_names):
    automation_status["running"] = True
    asyncio.run(automate_play_console(app_names))
    automation_status["running"] = False

DEFAULT_TIMEOUT = 30000

async def wait_for_element(page, selector, timeout=DEFAULT_TIMEOUT, state="visible"):
    """Wait for element with enhanced visibility checks"""
    try:
        element = await page.wait_for_selector(
            selector,
            timeout=timeout,
            state=state
        )
        await element.scroll_into_view_if_needed()
        return element
    except PlaywrightTimeoutError as e:
        print(f"⏰ Timeout {timeout}ms waiting for element: {selector}")
        raise
    except Exception as e:
        print(f"❌ Unexpected error waiting for element: {selector} - {str(e)}")
        raise

async def click_element(page, element, description=""):
    """Enhanced click with multiple fallback methods"""
    try:
        await element.click()
        print(f"✅ Clicked {description}")
    except Exception as click_error:
        try:
            await element.dispatch_event('click')
            print(f"ℹ️ Used dispatch_event for {description}")
        except Exception as dispatch_error:
            try:
                await page.evaluate("el => el.click()", element)
                print(f"ℹ️ Used JS click for {description}")
            except Exception as js_error:
                print(f"❌ Failed to click {description}")
                raise click_error

async def click_button_by_material_radio_debug_id(page, debug_id):
    selector = f"material-radio[debug-id='{debug_id}'] input[type='radio']"
    element = await wait_for_element(page, selector)
    await click_element(page, element, f"material-radio {debug_id}")

async def click_button_by_console_form_expandable_debug_id(page, debug_id):
    selector = f"console-form-expandable-section[debug-id='{debug_id}'] input[type='radio']"
    element = await wait_for_element(page, selector)
    await element.click()

async def click_button_by_material_radio_group_debug_id(page, debug_id, index=0):
    """
    Robust radio group click that:
    1. Uses existing wait_for_element function
    2. Waits for container to be visible
    3. Waits for specific radio button to be ready
    4. Provides clear debugging
    """
    # First wait for the container
    group_selector = f"material-radio-group[debug-id='{debug_id}']"
    try:
        group = await wait_for_element(page, group_selector)
        print(f"✅ Radio group container found: {debug_id}")
    except Exception as e:
        print(f"❌ Failed to find radio group container: {debug_id}")
        raise Exception(f"Radio group container '{debug_id}' not found") from e

    # Then wait for radio buttons
    radio_selector = f"{group_selector} input[type='radio'], {group_selector} [role='radio']"
    try:
        await wait_for_element(page, radio_selector)
        radio_buttons = await page.query_selector_all(radio_selector)
        
        if len(radio_buttons) <= index:
            raise Exception(f"Only found {len(radio_buttons)} radio buttons (needed index {index})")
        
        target = radio_buttons[index]
        await click_element(page, target, f"radio button {index} in group {debug_id}")
        
    except Exception as e:
        print(f"❌ Failed to click radio button: {debug_id} index {index}")
        # Debug what radio buttons were actually found
        found_count = len(await page.query_selector_all(radio_selector))
        print(f"  Found {found_count} radio buttons in group")
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
                        print(f"Radio button {radio_button_index + 1} clicked in parent index {parent_index}, group {i + 1}.")
            else:
                if len(material_radio_groups) > child_index:
                    group = material_radio_groups[child_index]
                    radio_buttons = await group.query_selector_all("input[type='radio']")
                    if len(radio_buttons) > radio_button_index:
                        await click_radio(radio_buttons[radio_button_index])
                        print(f"Radio button {radio_button_index + 1} clicked in parent index {parent_index}, child index {child_index}.")
    except Exception as e:
        print(f"Error while interacting: {e}")

async def click_button_by_xpath(page, xpath):
    """Enhanced XPath click with better waiting"""
    try:
        element = await wait_for_element(page, f'xpath={xpath}')
        await click_element(page, element, f"XPath {xpath}")
    except Exception as e:
        print(f"❌ XPath click failed: {xpath}")
        raise


async def click_checkbox_by_debug_id(page, debug_id, index=0):
    try:
        # Wait for container first
        container_selector = f"material-checkbox[debug-id='{debug_id}']"
        await wait_for_element(page, container_selector)
        
        checkboxes = await page.query_selector_all(container_selector)
        if index >= len(checkboxes):
            print(f"Invalid index {index}. Only {len(checkboxes)} checkboxes available.")
            return
            
        container = checkboxes[index]
        await page.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center' })", container)
        checkbox = await container.query_selector("input[type='checkbox']")
        await click_element(page, checkbox, f"checkbox {debug_id}")  # Use your click_element
        print(f"Checkbox {index} clicked.")
    except Exception as e:
        print(f"Checkbox click error: {e}")
        raise

async def upload_csv_from_static_file(page, filename, timeout=30000):
    """
    Upload CSV file from static folder with improved waiting and error handling.
    
    Args:
        page: Playwright page object
        filename: Name of file in static folder
        timeout: Maximum time to wait for file input (ms)
    """
    try:
        # Validate file exists
        static_folder = os.path.join(os.getcwd(), 'static')
        file_path = os.path.join(static_folder, filename)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found in static folder: {filename}")
        if not filename.lower().endswith('.csv'):
            print(f"⚠️ Warning: File '{filename}' may not be a CSV file")

        # Wait for file input to be present in DOM
        file_input_selector = "input[type='file']"
        
        try:
            file_input = await page.wait_for_selector(
                file_input_selector,
                state="attached",
                timeout=timeout
            )
            
            # Check if enabled
            is_disabled = await file_input.get_attribute("disabled")
            if is_disabled:
                raise Exception("File input is disabled!")
        except Exception as e:
            raise Exception(f"File input not ready for upload: {str(e)}")

        # Perform the upload with retry logic
        max_retries = 2
        for attempt in range(max_retries):
            try:
                await file_input.set_input_files(file_path)
                
                # Verify upload completed
                files = await file_input.input_value()
                if not files:
                    raise Exception("No files detected after upload")
                    
                print(f"✅ File '{filename}' uploaded successfully!")
                return
                
            except Exception as upload_error:
                if attempt == max_retries - 1:
                    raise
                print(f"⚠️ Upload attempt {attempt + 1} failed, retrying...")
                await asyncio.sleep(1)
                
    except FileNotFoundError as e:
        print(f"❌ File error: {e}")
        raise
    except Exception as e:
        print(f"❌ Upload failed: {str(e)}")
        raise

async def wait_for_login(page):
    """More reliable login detection"""
    print("🔐 Waiting for login... Please log in manually.")
    try:
        await page.wait_for_selector("#main-content", timeout=0)
        print("🔓 Login detected")
        # Additional verification
        await page.wait_for_function(
            "() => document.readyState === 'complete'",
            timeout=DEFAULT_TIMEOUT
        )
    except Exception as e:
        print(f"❌ Login verification failed: {str(e)}")
        raise

async def automate_play_console(app_names):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        context = await browser.new_context(no_viewport=True)
        page = await context.new_page()
        
        # Initial navigation to Play Console
        await page.goto("https://play.google.com/console/u/0/developers/8453266419614197800/create-new-app")
        
        # Wait for manual login
        print("Please log in manually in the browser window...")
        await page.wait_for_selector("#main-content", timeout=0)  # No timeout - waits forever
        
        print("Login detected, continuing automation...")
        
        for app_name in app_names:
            print(f"\n=== Processing app: {app_name} ===")
            
            try:
                # Navigate to create new app page at start of each iteration
                await page.goto("https://play.google.com/console/u/0/developers/8453266419614197800/create-new-app")
                await page.wait_for_selector("#main-content", state="visible", timeout=DEFAULT_TIMEOUT)
                
                # Clear and fill the app name field
                input_xpath = '//*[@id="main-content"]/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/create-new-app-page/console-form/console-form-row[1]/div/div[2]/div[1]/material-input/label/input'
                input_field = await wait_for_element(page, f'xpath={input_xpath}')
                
                # Clear the field first in case there's existing text
                await input_field.fill("")
                await asyncio.sleep(0.5)  # Small delay to ensure field is cleared
                
                # Fill with new app name
                await input_field.fill(app_name)
                await asyncio.sleep(0.5)

                print(f"App name '{app_name}' entered successfully.")

                await click_button_by_material_radio_debug_id(page, "app-radio")
                print("Radio button 'app-radio' clicked.")

                await click_button_by_material_radio_debug_id(page, "free-radio")
                print("Radio button 'free-radio' clicked.")

                # Check "guidelines-checkbox"
                await click_checkbox_by_debug_id(page, "guidelines-checkbox")

                # Check "export-laws-checkbox"
                await click_checkbox_by_debug_id(page, "export-laws-checkbox")

                # Create App button
                await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/create-new-app-page/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div/material-button[1]/button/div[2]")

                # Click on the View Tasks
                await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/div/console-button-set/div/button/material-icon/i")

                # Click on the Set privacy policy
                await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/expandable-container/div/div/div/div/task-group[1]/div[2]/div/task[1]/div/div[2]/div/material-icon/i")

                # Flipdish privacy policy URL
                input_xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-privacy-policy-page/div/console-block-1-column[2]/div/div/console-form/material-input/label/input"
                text_field = await wait_for_element(page, f'xpath={input_xpath}')
                await text_field.fill("https://www.flipdish.com/privacy-policy")

                # Save button
                await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-privacy-policy-page/div/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span")
                await asyncio.sleep(5)

                # Dashboard button
                await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-privacy-policy-page/console-page-header/div/div/div/console-button-set/div/a/material-icon/i")

                # App access
                await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/expandable-container/div/div/div/div/task-group[1]/div[2]/div/task[2]/div/div[2]/div/material-icon/i")

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

                print("Instructions entered successfully.")

                # No additional information needed - Checkbox
                await click_checkbox_by_debug_id(page, "no-additional-details-required-checkbox")

                # Add
                await click_button_by_xpath(page, "//*[@id='default-acx-overlay-container']/div[2]/div/focus-trap/div[2]/relative-popup/div/span/div/div[2]/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div/button[1]/span")

                # Save button
                await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-testing-credentials-page/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span")
                await asyncio.sleep(5)

                # Dashboard button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-testing-credentials-page/console-page-header/div/div/div/console-button-set/div/a/material-icon/i")
                except Exception as e:
                    print("Normal click failed, trying JavaScript click...")
                    button = await page.wait_for_selector("xpath=//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-testing-credentials-page/console-page-header/div/div/div/console-button-set/div/a/material-icon/i", timeout=5000)
                    await page.evaluate("""
                        (btn) => {
                            ['click', 'mousedown', 'mouseup', 'mouseenter', 'mouseleave'].forEach(event => {
                                const evt = new MouseEvent(event, { bubbles: true, cancelable: true });
                                btn.dispatchEvent(evt);
                            });
                        }
                    """, button)
                    print("JavaScript click executed successfully.")


                # Ads
                await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/expandable-container/div/div/div/div/task-group[1]/div[2]/div/task[3]/div/div[2]/div/material-icon/i")

                # No ads
                await click_button_by_material_radio_group_debug_id(page, "contains-ads-radio-group", index=1)

                # Save button
                await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-ads-declaration-page/div/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span")
                await asyncio.sleep(5)

                # Dashboard button
                await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-ads-declaration-page/console-page-header/div/div/div/console-button-set/div/a/material-icon/i")

                # Content ratings
                await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/expandable-container/div/div/div/div/task-group[1]/div[2]/div/task[4]/div/div[2]/div/material-icon/i")

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
                await asyncio.sleep(5)

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
                await asyncio.sleep(5)

                # Dashboard button
                try:
                    xpath = "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-rating-overview-page/console-page-header/div/div/div/console-button-set/div/a/material-icon/i"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Target audience and content button
                try:
                    xpath = "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/expandable-container/div/div/div/div/task-group[1]/div[2]/div/task[5]/div/div[2]/div/material-icon/i"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the button: {e}")

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
                await asyncio.sleep(5)                   

                # Dashboard button
                try:
                    xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-target-audience-content-page/console-page-header/div/div/div/console-button-set/div/a/material-icon/i"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the button: {e}")

                # # News app button
                # try:
                #     xpath = "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/expandable-container/div/div/div/div/task-group[1]/div[2]/div/task[6]/div/div[2]/div/material-icon/i"
                #     await click_button_by_xpath(page, xpath)
                # except Exception as e:
                #     print(f"Failed to click the element: {e}")

                # # No News app button
                # await click_button_by_material_radio_group_debug_id(page, "app-type-radio-group", index=0)

                # # Save button
                # try:
                #     xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-news-declaration-page/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span"
                #     await click_button_by_xpath(page, xpath)
                # except Exception as e:
                #     print(f"Failed to click the element: {e}")
                # await asyncio.sleep(5)

                # # Dashboard button
                # try:
                #     xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-news-declaration-page/console-page-header/div/div/div/console-button-set/div/a/material-icon/i"
                #     await click_button_by_xpath(page, xpath)
                # except Exception as e:
                #     print(f"Failed to click the element: {e}")

                # Data safety button
                try:
                    xpath = "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/expandable-container/div/div/div/div/task-group[1]/div[2]/div/task[6]/div/div[2]/div/material-icon/i"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Import button
                try:
                    xpath = "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-play-safety-labels-page/console-page-header/div/div/div/console-header/div/div/div[1]/div[2]/div/div/console-button-set/div/button[2]/span"
                    await click_button_by_xpath(page, xpath)
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Upload file
                filename = "data_safety_export_Jan24.csv"
                await upload_csv_from_static_file(page, filename)

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

                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-play-safety-labels-page/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[1]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-play-safety-labels-page/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[1]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-play-safety-labels-page/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[1]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Save button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-play-safety-labels-page/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[3]/overflowable-item[3]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(5)

                # Dashboard button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-play-safety-labels-page/console-page-header/div/div/div/console-button-set/div/a/material-icon/i")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Government app button
                try:
                    await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/expandable-container/div/div/div/div/task-group[1]/div[2]/div/task[7]/div/div[2]/div/material-icon/i")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # No government app button
                await click_button_by_material_radio_debug_id(page, "no-radio")
                print("Radio button 'no-radio' clicked.")

                # Save button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-government-apps-page/publishing-bottom-bar/form-bottom-bar/bottom-bar-base/div/div/div/div[2]/console-button-set/div[2]/overflowable-item[2]/button/span")
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(5)

                # Dashboard button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-government-apps-page/console-page-header/div/div/div/console-button-set/div/a/material-icon/i")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Financial features button
                try:
                    await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/expandable-container/div/div/div/div/task-group[1]/div[2]/div/task[8]/div/div[2]/div/material-icon/i")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

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
                await asyncio.sleep(5)

                # Dashboard button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-finance-declaration-page/console-page-header/div/div/div/console-button-set/div/a/material-icon/i")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Health apps button
                try:
                    await click_button_by_xpath(page, " /html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/expandable-container/div/div/div/div/task-group[1]/div[2]/div/task[9]/div/div[2]/div/material-icon/i")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

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
                await asyncio.sleep(5)

                # Dashboard button
                try:
                    await click_button_by_xpath(page, "//*[@id='main-content']/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-content-health-page/console-page-header/div/div/div/console-button-set/div/a/material-icon/i")
                except Exception as e:
                    print(f"Failed to click the element: {e}")

                # Store settings button
                try:
                    await click_button_by_xpath(page, "/html/body/div[1]/root/console-chrome/div/div/div/div[1]/div/div[1]/page-router-outlet/page-wrapper/div/app-dashboard-page/console-section[2]/div/div/console-block-1-column/div/div/setup-goal/goal/div/div[2]/expandable-area/expandable-container/div/div/div/div/task-group[2]/div[2]/div/task[1]/div/div[2]/div/material-icon/i")
                except Exception as e:
                    print(f"Failed to click the element: {e}")
                await asyncio.sleep(5)

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

                print(f"=== Completed processing for app: {app_name} ===")
                
            except Exception as e:
                print(f"Error for {app_name}: {e}")
                # Even if there was an error, try to continue with next app
                continue

        await browser.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run_automation', methods=['POST'])
def run_automation():
    app_names_input = request.form.get("app_names")
    if app_names_input:
        app_names = [name.strip() for name in app_names_input.split("\n") if name.strip()]
        thread = Thread(target=run_automation_in_thread, args=(app_names,))
        thread.start()
        return jsonify({"status": "success", "message": "Automation started!"})
    return jsonify({"status": "error", "message": "No app names provided!"})

@app.route('/automation_status', methods=['GET'])
def automation_status_check():
    return jsonify({"running": automation_status["running"]})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

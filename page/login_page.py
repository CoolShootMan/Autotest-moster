
import re
from playwright.sync_api import Page, expect

class LoginPage:
    def __init__(self, page: Page):
        self.page = page
        # Locators based on user-provided XPaths
        self.account_input = "xpath=//input[@name='phoneNumber']"
        self.password_input = "xpath=//input[@name='password']"
        self.switch_to_password_mode_link = "xpath=/html/body/div/div/div[2]/div/div/div/div[2]/p[1]" # Reverted to absolute path as text-based failed
        self.login_button = "xpath=/html/body/div/div/div[2]/div/div/div/form/div/button"

        # The following locators are kept for reference but are less stable
        self.switch_account_format_button_abs = "xpath=/html/body/div/div/div[2]/div/div/div/form/div/div/div/button"
        self.send_code_button_abs = "xpath=/html/body/div/div/div[2]/div/div/div/form/div/button"

    def navigate(self, url="https://release.pear.us/login"):
        """Navigates to the login page."""
        self.page.goto(url)

    def switch_to_password_login(self):
        """Switches the login form to password mode."""
        self.page.locator(self.switch_to_password_mode_link).click()

    def enter_username(self, username: str):
        """Enters the username into the account input field."""
        self.page.locator(self.account_input).fill(username)

    def enter_password(self, password: str):
        """Enters the password into the password input field."""
        self.page.locator(self.password_input).fill(password)

    def click_login(self):
        """Clicks the login button."""
        self.page.locator(self.login_button).click()

    def login(self, username: str, password: str):
        """Performs the full login sequence."""
        print("Navigating to login page...")
        self.navigate()
        expect(self.page).to_have_url(re.compile(".*login.*"), timeout=10000)
        print("Login page loaded.")
        print("Switching to password login mode...")
        self.switch_to_password_login()
        expect(self.page.locator(self.password_input)).to_be_visible(timeout=10000)
        print("Switched to password login mode, password input visible.")
        print(f"Entering username: {username}...")
        self.enter_username(username)
        print("Entering password...")
        self.enter_password(password)
        print("Clicking login button...")
        self.click_login()
        print("Login process submitted. Waiting for navigation after login...")
        # Wait for the URL to change away from the login page
        self.page.wait_for_url(re.compile("^(?!.*login).*$"), timeout=30000)
        # Fallback for wait_for_loadstate: wait for a common element on the next page to be visible
        # This assumes after login, a main content area or a specific element will appear.
        # For now, we'll wait for the 'Customize' button on the My Shop page as a general indicator.
        self.page.wait_for_selector("xpath=/html/body/div[1]/section/div/div/div[2]/div[2]/div[1]/div[2]/div[2]/button[1]", timeout=30000)
        print("Navigation after login successful and page is stable.")
        # TODO: Add a specific assertion for a unique element on the post-login page
        # For example: expect(self.page.get_by_text("Welcome, User!")).to_be_visible()
        # For now, we'll just assert the URL is not the login page (already done by wait_for_url)
        print("Login successful: Post-login page loaded and stable.")


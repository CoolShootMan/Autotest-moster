from playwright.sync_api import Page, expect

class MyShopPage:
    def __init__(self, page: Page):
        self.page = page
        # Locator from Playwright recording
        self.customize_button = self.page.locator("xpath=/html/body/div[1]/section/div/div/div[2]/div[2]/div[1]/div[2]/div[2]/button[1]")

    def click_customize_shop(self):
        """Clicks the button and waits for the customization page to load."""
        print("Clicking 'Customize Shop' button and waiting for navigation...")
        with self.page.expect_navigation(url="https://release.pear.us/storefront-modules#Storefront"):
            self.customize_button.click()
        print("Navigation to Customize Shop page successful.")
        # Assert that a key element on the Customize Shop page is visible
        expect(self.page.get_by_role("tab", name="Modules")).to_be_visible(timeout=10000)
        print("Customize Shop page loaded and 'Modules' tab is visible.")

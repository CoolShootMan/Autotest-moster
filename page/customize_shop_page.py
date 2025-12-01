from playwright.sync_api import Page, expect

class CustomizeShopPage:
    def __init__(self, page: Page):
        self.page = page
        # Locators from Playwright recording
        self.modules_tab = page.get_by_role("tab", name="Modules")
        self.add_new_module_button = page.get_by_role("button", name="Add new module")
        self.title_input = page.get_by_role("textbox", name="Enter title of the module")
        self.add_button = page.get_by_role("button", name="Add")
        self.add_from_my_posts_button = page.get_by_role("button", name="Add from my posts") # Added missing locator
        # The recording selected specific items, we will generalize this if needed
        self.first_item_to_add = page.get_by_role("button", name="Image of Product test date zasq9n")
        self.second_item_to_add = page.get_by_role("button", name="Image of Product test 7801")
        self.publish_button = page.get_by_role("button", name="Publish")

    def go_to_modules_tab(self):
        print("Waiting for 'Modules' tab to be visible...")
        expect(self.modules_tab).to_be_visible(timeout=15000)
        print("Navigating to Modules tab...")
        self.modules_tab.click()
        expect(self.add_new_module_button).to_be_visible(timeout=10000)
        print("Modules tab clicked and 'Add new module' button is visible.")
    def start_add_new_module(self):
        print("Clicking 'Add new module'...")
        self.add_new_module_button.click()
        expect(self.title_input).to_be_visible(timeout=10000)
        print("'Add new module' form is visible.")
    def fill_module_and_add(self, title: str):
        print(f"Filling module title: {title}")
        self.title_input.click()
        self.title_input.fill(title)
        print("Clicking 'Add' button...")
        self.add_button.click()
        # Assert that a key element inside the pop-up is visible, confirming the pop-up has appeared.
        # The recording shows clicking "Image of Product test date zasq9n" inside the pop-up.
        expect(self.first_item_to_add).to_be_visible(timeout=10000)
        print("'Select from my posts' pop-up appeared and is visible.")
    def add_items_to_module(self):
        print("Adding items to the new module...")
        # The 'Select from my posts' pop-up appears automatically for new modules.
        # Proceed directly to selecting items.
        self.first_item_to_add.click()
        self.second_item_to_add.click()
        # Then click the "Add" button in the dialog
        self.add_button.click()
        # After adding items, assert that the dialog is gone and the Publish button is visible
        expect(self.publish_button).to_be_visible(timeout=10000)
        print("Items added and 'Publish' button is visible.")
    def publish_changes(self):
        print("Publishing changes...")
        self.publish_button.click()
        # TODO: Add a specific assertion for publish success (e.g., success message, element disappearance)
        self.page.wait_for_timeout(2000) # Small pause to allow any success message to appear
        print("Changes published (verification needed).")
    def verify_module_visible(self, title: str):
        print(f"Verifying module '{title}' is visible...")
        # Use the recorded locator and .first to resolve strict mode violation
        module_locator = self.page.get_by_role("paragraph").filter(has_text=title).first
        expect(module_locator).to_be_visible(timeout=10000)

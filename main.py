"""Food Donation Management System - backend prototype (console front end).
 
Run:  python main.py
The console is only a thin layer; all rules live in the food_donation package.
"""
from pathlib import Path
 
from food_donation import views
from food_donation.exceptions import FoodDonationError, StorageError, ValidationError
from food_donation.location_service import LocationService
from food_donation.models import Role, format_phone
from food_donation.services import DonationService, UserService
from food_donation.storage import DonationRepository, UserRepository
from food_donation.validators import (
    parse_available_until,
    parse_quantity,
    validate_food_name,
    validate_location,
    validate_person_name,
    validate_phone,
)
 
DATA_DIR = Path(__file__).with_name("data")
 
 
class ConsoleApp:
    def __init__(self, user_service, donation_service):
        self.users = user_service
        self.donations = donation_service
        self.current_user = None
 
    # ---- input helpers -----------------------------------------------------------
    @staticmethod
    def ask(prompt, validate=None, default=None):
        """Ask until the answer passes validation. Enter returns the default if given."""
        while True:
            raw = input(prompt).strip()
            if not raw and default is not None:
                return default
            try:
                return validate(raw) if validate else raw
            except ValidationError as error:
                print(f"  {error}")
 
    @staticmethod
    def choose(prompt, options):
        valid = [key for key, _ in options]
        while True:
            choice = input(prompt).strip()
            if choice in valid:
                return choice
            print(f"Invalid option. Choose {valid[0]}-{valid[-1]}.")
 
    def run_safely(self, action):
        try:
            action()
        except FoodDonationError as error:
            print(f"Error: {error}")
 
    # ---- main menu ---------------------------------------------------------------
    def start(self, warnings=()):
        print("Food Donation Management System (Prototype)")
        for warning in warnings:
            print(f"Warning: {warning}")
        while True:
            if self.current_user:
                self.role_menu()
                continue
            options = [("1", "Register User"), ("2", "Login"), ("3", "Track Donation"),
                       ("4", "View All Donations"), ("5", "View Users"), ("6", "Exit")]
            print("\nMain Menu")
            for key, label in options:
                print(f"{key}. {label}")
            choice = self.choose("Enter your choice (1-6): ", options)
            if choice == "6":
                print("All records are saved. Goodbye!")
                return
            self.run_safely({"1": self.register, "2": self.login, "3": self.track_donation,
                             "4": self.view_all, "5": self.view_users}[choice])
 
    def register(self):
        print("\nRegister User")
        role = self.ask("Role (Donor/Volunteer/Requester): ", Role.parse)
        name = self.ask("Name: ", validate_person_name)
        phone = self.ask("Phone: ", self.new_phone)
        location = self.ask("Location: ", validate_location)
        user = self.users.register(role, name=name, phone=phone, location=location)
        print(f"Registered successfully. Your {user.role.value} ID is {user.user_id}.")
 
    def new_phone(self, value):
        """Validate a phone number and make sure nobody has registered it yet."""
        phone = validate_phone(value)
        existing = self.users.find_by_phone(phone)
        if existing:
            raise ValidationError(f"This number is already registered to {existing.user_id}. "
                                  "Use a different number, or log in with that ID.")
        return phone
 
    def login(self):
        self.current_user = self.users.get(self.ask("Enter your User ID: "))
        print(f"Welcome, {self.current_user.name} ({self.current_user.role.value}).")
 
    def track_donation(self):
        donation = self.donations.get(self.ask("Enter Donation ID: "))
        donor = self.users.users.get(donation.donor_id)
        volunteer = self.users.users.get(donation.volunteer_id) if donation.volunteer_id else None
        print()
        print(views.donation_details(donation, donor, volunteer))
 
    def view_all(self):
        print("\nAll Donations")
        print(views.donation_table(self.donations.all()))
        print()
        print(views.status_summary(self.donations.status_summary()))
 
    def view_users(self):
        print("\nRegistered Users")
        print(views.user_table(self.users.all()))
 
    # ---- role menus --------------------------------------------------------------
    def role_menu(self):
        user = self.current_user
        menus = {
            Role.DONOR: [("1", "Create Donation", self.create_donation),
                         ("2", "My Donations", self.my_donations),
                         ("3", "Cancel Donation", self.cancel_donation)],
            Role.VOLUNTEER: [("1", "View Available Donations", self.view_available),
                             ("2", "Claim Donation", self.claim),
                             ("3", "Mark Picked Up", self.picked_up),
                             ("4", "Mark Delivered", self.delivered),
                             ("5", "Release Donation", self.release),
                             ("6", "My Claimed Donations", self.my_claims)],
            Role.REQUESTER: [("1", "View Available Donations", self.view_available)],
        }[user.role]
        menu = menus + [(str(len(menus) + 1), "Logout", None)]
        print(f"\n{user.role.value} Menu - {user.user_id} ({user.name})")
        for key, label, _ in menu:
            print(f"{key}. {label}")
        choice = self.choose(f"Enter your choice (1-{len(menu)}): ", [(k, l) for k, l, _ in menu])
        action = next(a for k, _, a in menu if k == choice)
        if action is None:
            print("Logged out.")
            self.current_user = None
        else:
            self.run_safely(action)
 
    # donor -------------------------------------------------------------------------
    def create_donation(self):
        donor = self.current_user
        print("\nCreate Donation")
        food = self.ask("Food Name: ", validate_food_name)
        quantity = self.ask("Quantity: ", lambda v: (parse_quantity(v), v)[1])
        location = self.ask("Location: ", validate_location)
        until = self.ask("Available Until: ", parse_available_until)
        phone = self.ask(f"Contact Number [{format_phone(donor.phone)}]: ",
                         validate_phone, default=donor.phone)
        donation, location_note = self.donations.create_donation(
            donor.user_id, food, quantity, location, until, contact_phone=phone)
        print()
        print(views.donation_created(donation))
        if location_note:
            print(location_note)
 
    def my_donations(self):
        print("\nMy Donations")
        print(views.donation_table(self.donations.donations_by_donor(self.current_user.user_id)))
 
    def cancel_donation(self):
        donation_id = self.ask("Enter Donation ID to cancel: ")
        if input(f"Cancel {donation_id.upper()}? (y/n): ").strip().lower() in ("y", "yes"):
            donation = self.donations.cancel(donation_id, self.current_user.user_id)
            print(views.status_update(donation))
        else:
            print("Nothing changed.")
 
    # volunteer / requester ----------------------------------------------------------
    def view_available(self):
        print()
        print(views.available_donations(self.donations.available_donations()))
 
    def claim(self):
        donation = self.donations.claim(self.ask("Enter Donation ID to claim: "),
                                        self.current_user.user_id)
        print()
        print(views.status_update(donation))
        print(f"Pickup contact: {donation.contact_name}, {format_phone(donation.contact_phone)}")
 
    def picked_up(self):
        donation = self.donations.mark_picked_up(self.ask("Enter Donation ID picked up: "),
                                                 self.current_user.user_id)
        print()
        print(views.status_update(donation))
 
    def delivered(self):
        donation = self.donations.mark_delivered(self.ask("Enter Donation ID delivered: "),
                                                 self.current_user.user_id)
        print()
        print(views.status_update(donation))
 
    def release(self):
        donation = self.donations.release(self.ask("Enter Donation ID to release: "),
                                          self.current_user.user_id)
        print()
        print(views.status_update(donation))
 
    def my_claims(self):
        print("\nMy Claimed Donations")
        print(views.donation_table(self.donations.donations_by_volunteer(self.current_user.user_id)))
 
 
def build_app(data_dir=DATA_DIR, location_service=None):
    """Wire the layers together. Returns (app, load_warnings)."""
    user_repo = UserRepository(Path(data_dir) / "users.json")
    donation_repo = DonationRepository(Path(data_dir) / "donations.json")
    warnings = []
    for repo in (user_repo, donation_repo):
        try:
            warnings += repo.load()
        except StorageError as error:
            warnings.append(f"{error} Starting with no records in that file.")
    user_service = UserService(user_repo)
    donation_service = DonationService(donation_repo, user_service,
                                       location_service or LocationService())
    return ConsoleApp(user_service, donation_service), warnings
 
 
def main():
    app, warnings = build_app()
    try:
        app.start(warnings)
    except (KeyboardInterrupt, EOFError):
        print("\nProgram stopped. Saved records are kept.")
 
 
if __name__ == "__main__":
    main()
 
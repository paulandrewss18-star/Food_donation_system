"""Business workflow. The CLI (or a future web/mobile API) calls only these
services; they apply the rules, keep records consistent and save to disk."""
from datetime import datetime
 
from .exceptions import (
    DonationNotFoundError,
    DuplicateUserError,
    LocationNotFoundError,
    LocationServiceError,
    PermissionDeniedError,
    StorageError,
    UserNotFoundError,
    ValidationError,
)
from .models import Donation, DonationStatus, Role, User
from .validators import (
    parse_available_until,
    validate_location,
    validate_person_name,
    validate_phone,
)
 
 
class UserService:
    def __init__(self, users):
        self.users = users
 
    def register(self, role, name, phone, location):
        role = Role.parse(role) if not isinstance(role, Role) else role
        user_class = User._registry[role]
        phone = validate_phone(phone)
        existing = self.find_by_phone(phone)
        if existing:
            raise DuplicateUserError(
                f"Phone number {phone[:5]} {phone[5:]} is already registered to {existing.user_id}.")
        user = user_class(
            user_id=self.users.next_id(user_class.ID_PREFIX, user_class.ID_START),
            name=validate_person_name(name),
            phone=phone,
            location=validate_location(location),
        )
        self.users.add(user)
        try:
            self.users.save()
        except StorageError:
            self.users.remove(user.user_id)
            raise
        return user
 
    def find_by_phone(self, phone):
        phone = validate_phone(phone)
        return next((u for u in self.users.all() if u.phone == phone), None)
 
    def get(self, user_id):
        user = self.users.get(user_id)
        if user is None:
            raise UserNotFoundError(f"No user found with ID '{user_id}'.")
        return user
 
    def get_with_role(self, user_id, role):
        user = self.get(user_id)
        if user.role is not role:
            raise PermissionDeniedError(f"{user.user_id} is a {user.role.value}, not a {role.value}.")
        return user
 
    def all(self):
        return self.users.all()
 
 
class DonationService:
    def __init__(self, donations, user_service, location_service=None, clock=datetime.now):
        self.donations = donations
        self.user_service = user_service
        self.location_service = location_service
        self.clock = clock
 
    # ---- helpers -----------------------------------------------------------------
    def _save_or_rollback(self, donation, snapshot):
        """Save all donations; if that fails, restore the donation's previous state."""
        try:
            self.donations.save()
        except StorageError:
            if snapshot is None:
                self.donations.remove(donation.donation_id)
            else:
                self.donations.replace(Donation.from_dict(snapshot))
            raise
 
    def refresh_expired(self):
        """Move uncollected donations past their time to Expired. Returns their IDs."""
        now = self.clock()
        expired = [d for d in self.donations.all() if d.expire_if_due(now)]
        if expired:
            self.donations.save()
        return [d.donation_id for d in expired]
 
    def get(self, donation_id):
        self.refresh_expired()
        donation = self.donations.get(donation_id)
        if donation is None:
            raise DonationNotFoundError(f"No donation found with ID '{donation_id}'.")
        return donation
 
    def _check_location(self, location):
        """Ask the API for coordinates. Never blocks donation creation."""
        if self.location_service is None:
            return None, None
        try:
            details = self.location_service.verify(location)
            place = ", ".join(p for p in (details["name"], details["state"], details["country"]) if p)
            return details, f"Location verified: {place}"
        except LocationNotFoundError:
            return None, "Note: location could not be found on the map; saved as entered."
        except LocationServiceError as error:
            return None, f"Note: location check skipped ({error})"
 
    # ---- donor actions ---------------------------------------------------------
    def create_donation(self, donor_id, food_name, quantity, location, available_until,
                        contact_phone=None, contact_name=None, notes=""):
        """Returns (donation, location_message)."""
        donor = self.user_service.get(donor_id)
        if not donor.can_create_donation():
            raise PermissionDeniedError(f"Only donors can create donations ({donor.user_id} is a {donor.role.value}).")
        now = self.clock()
        until = available_until if isinstance(available_until, datetime) \
            else parse_available_until(available_until, now)
        if until <= now:
            raise ValidationError("Available-until time must be in the future.")
 
        donation = Donation(
            donation_id=self.donations.next_id("DON"),
            donor_id=donor.user_id,
            food_name=food_name,
            quantity=quantity,
            location=location,
            available_until=until,
            contact_name=contact_name or donor.name,
            contact_phone=contact_phone or donor.phone,
            notes=notes,
        )
        donation.location_details, message = self._check_location(donation.location)
        self.donations.add(donation)
        self._save_or_rollback(donation, snapshot=None)
        return donation, message
 
    def cancel(self, donation_id, donor_id):
        donor = self.user_service.get_with_role(donor_id, Role.DONOR)
        donation = self.get(donation_id)
        snapshot = donation.to_dict()
        donation.cancel(donor)
        self._save_or_rollback(donation, snapshot)
        return donation
 
    def donations_by_donor(self, donor_id):
        self.refresh_expired()
        return [d for d in self.donations.all() if d.donor_id == donor_id.upper()]
 
    # ---- volunteer actions -----------------------------------------------------
    def available_donations(self):
        """Available donations, the ones expiring soonest first."""
        self.refresh_expired()
        return sorted((d for d in self.donations.all() if d.status is DonationStatus.AVAILABLE),
                      key=lambda d: d.available_until)
 
    def _volunteer_action(self, donation_id, volunteer_id, action):
        volunteer = self.user_service.get_with_role(volunteer_id, Role.VOLUNTEER)
        donation = self.get(donation_id)
        snapshot = donation.to_dict()
        action(donation, volunteer)
        self._save_or_rollback(donation, snapshot)
        return donation
 
    def claim(self, donation_id, volunteer_id):
        return self._volunteer_action(donation_id, volunteer_id,
                                      lambda d, v: d.claim(v, self.clock()))
 
    def release(self, donation_id, volunteer_id):
        return self._volunteer_action(donation_id, volunteer_id, lambda d, v: d.release(v))
 
    def mark_picked_up(self, donation_id, volunteer_id):
        return self._volunteer_action(donation_id, volunteer_id, lambda d, v: d.mark_picked_up(v))
 
    def mark_delivered(self, donation_id, volunteer_id):
        return self._volunteer_action(donation_id, volunteer_id, lambda d, v: d.mark_delivered(v))
 
    def donations_by_volunteer(self, volunteer_id):
        self.refresh_expired()
        return [d for d in self.donations.all() if d.volunteer_id == volunteer_id.upper()]
 
    # ---- reporting ---------------------------------------------------------------
    def all(self):
        self.refresh_expired()
        return self.donations.all()
 
    def status_summary(self):
        counts = {status: 0 for status in DonationStatus}
        for donation in self.all():
            counts[donation.status] += 1
        return counts
 

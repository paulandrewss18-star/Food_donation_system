"""Domain models: user roles (inheritance) and the Donation workflow (state machine)."""
from datetime import datetime
from enum import Enum

from .exceptions import (
    InvalidStatusTransitionError,
    PermissionDeniedError,
    ValidationError,
)
from .validators import (
    parse_quantity,
    validate_food_name,
    validate_location,
    validate_person_name,
    validate_phone,
)


def _now():
    return datetime.now().replace(microsecond=0)


def _parse_iso(value, field):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError(f"Invalid date/time for {field}: {value!r}") from None


def format_phone(digits):
    return f"{digits[:5]} {digits[5:]}"


# =============================================================================
# Users
# =============================================================================

class Role(Enum):
    DONOR = "Donor"
    VOLUNTEER = "Volunteer"
    REQUESTER = "Requester"

    @classmethod
    def parse(cls, value):
        for role in cls:
            if str(value).strip().casefold() == role.value.casefold():
                return role
        raise ValidationError(f"Role must be one of: {', '.join(r.value for r in cls)}.")


class User:
    """Common details for every person using the system."""

    ROLE = None
    ID_PREFIX = None
    ID_START = 1
    _registry = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.ROLE is not None:
            User._registry[cls.ROLE] = cls

    def __init__(self, user_id, name, phone, location, created_at=None):
        if not isinstance(user_id, str) or not user_id.upper().startswith(self.ID_PREFIX):
            raise ValidationError(f"{self.ROLE.value} IDs must start with {self.ID_PREFIX}.")
        self._user_id = user_id.upper()
        self.name = name
        self.phone = phone
        self.location = location
        self.created_at = created_at or _now()

    @property
    def user_id(self):
        return self._user_id

    @property
    def role(self):
        return self.ROLE

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = validate_person_name(value)

    @property
    def phone(self):
        return self._phone

    @phone.setter
    def phone(self, value):
        self._phone = validate_phone(value)

    @property
    def location(self):
        return self._location

    @location.setter
    def location(self, value):
        self._location = validate_location(value)

    # Permissions: each role overrides what it is allowed to do.
    def can_create_donation(self):
        return False

    def can_handle_delivery(self):
        return False

    def can_view_available(self):
        return True

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "role": self.role.value,
            "name": self.name,
            "phone": self.phone,
            "location": self.location,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValidationError("User record must be a JSON object.")
        try:
            subclass = User._registry[Role.parse(data.get("role", ""))]
            return subclass(
                user_id=data["user_id"],
                name=data["name"],
                phone=data["phone"],
                location=data["location"],
                created_at=_parse_iso(data["created_at"], "created_at") if data.get("created_at") else None,
            )
        except KeyError as missing:
            raise ValidationError(f"User record is missing {missing}.") from None

    def __str__(self):
        return f"{self.user_id} - {self.name} ({self.role.value})"


class Donor(User):
    ROLE = Role.DONOR
    ID_PREFIX = "DNR"
    ID_START = 1

    def can_create_donation(self):
        return True


class Volunteer(User):
    ROLE = Role.VOLUNTEER
    ID_PREFIX = "VOL"
    ID_START = 101

    def can_handle_delivery(self):
        return True


class Requester(User):
    """Organisation or person receiving food. Read-only in this prototype;
    the final app will let requesters raise food requests."""
    ROLE = Role.REQUESTER
    ID_PREFIX = "REQ"
    ID_START = 1


# =============================================================================
# Donations
# =============================================================================

class DonationStatus(Enum):
    AVAILABLE = "Available"
    CLAIMED = "Claimed"
    PICKED_UP = "Picked Up"
    DELIVERED = "Delivered"
    CANCELLED = "Cancelled"
    EXPIRED = "Expired"

    @property
    def is_final(self):
        return not ALLOWED_TRANSITIONS[self]


# Available -> Claimed -> Picked Up -> Delivered, plus release, cancel and expiry.
ALLOWED_TRANSITIONS = {
    DonationStatus.AVAILABLE: {DonationStatus.CLAIMED, DonationStatus.CANCELLED, DonationStatus.EXPIRED},
    DonationStatus.CLAIMED: {DonationStatus.PICKED_UP, DonationStatus.AVAILABLE,
                             DonationStatus.CANCELLED, DonationStatus.EXPIRED},
    DonationStatus.PICKED_UP: {DonationStatus.DELIVERED},
    DonationStatus.DELIVERED: set(),
    DonationStatus.CANCELLED: set(),
    DonationStatus.EXPIRED: set(),
}


class StatusChange:
    """One entry in a donation's history."""

    def __init__(self, status, changed_by, at=None, note=""):
        self.status = status
        self.changed_by = changed_by
        self.at = at or _now()
        self.note = note

    def to_dict(self):
        return {"status": self.status.value, "changed_by": self.changed_by,
                "at": self.at.isoformat(), "note": self.note}

    @classmethod
    def from_dict(cls, data):
        return cls(DonationStatus(data["status"]), data["changed_by"],
                   _parse_iso(data["at"], "history time"), data.get("note", ""))


class Donation:
    """A food donation. Its status can only change through the workflow
    methods (claim, mark_picked_up, ...), which check the rules."""

    def __init__(self, donation_id, donor_id, food_name, quantity, location,
                 available_until, contact_name, contact_phone, notes="",
                 location_details=None, status=DonationStatus.AVAILABLE,
                 volunteer_id=None, created_at=None, history=None):
        self._donation_id = donation_id
        self._donor_id = donor_id
        self.food_name = food_name
        self.quantity, self.unit = parse_quantity(quantity)
        self.location = location
        self.available_until = available_until
        self.contact_name = contact_name
        self.contact_phone = contact_phone
        self.notes = (notes or "").strip()
        self.location_details = location_details
        self._status = status
        self._volunteer_id = volunteer_id
        self.created_at = created_at or _now()
        self._history = history if history is not None else [
            StatusChange(status, donor_id, self.created_at, "Donation created")]

    # ---- read-only identity and workflow state ------------------------------
    @property
    def donation_id(self):
        return self._donation_id

    @property
    def donor_id(self):
        return self._donor_id

    @property
    def status(self):
        return self._status

    @property
    def volunteer_id(self):
        return self._volunteer_id

    @property
    def history(self):
        return tuple(self._history)

    # ---- validated attributes ------------------------------------------------
    @property
    def food_name(self):
        return self._food_name

    @food_name.setter
    def food_name(self, value):
        self._food_name = validate_food_name(value)

    @property
    def location(self):
        return self._location

    @location.setter
    def location(self, value):
        self._location = validate_location(value)

    @property
    def available_until(self):
        return self._available_until

    @available_until.setter
    def available_until(self, value):
        if not isinstance(value, datetime):
            raise ValidationError("Available-until must be a date and time.")
        self._available_until = value.replace(second=0, microsecond=0)

    @property
    def contact_name(self):
        return self._contact_name

    @contact_name.setter
    def contact_name(self, value):
        self._contact_name = validate_person_name(value)

    @property
    def contact_phone(self):
        return self._contact_phone

    @contact_phone.setter
    def contact_phone(self, value):
        self._contact_phone = validate_phone(value)

    # ---- derived values ------------------------------------------------------
    @property
    def quantity_text(self):
        return f"{self.quantity:g} {self.unit}"

    @property
    def location_verified(self):
        return bool(self.location_details)

    def is_past_expiry(self, now=None):
        return (now or datetime.now()) >= self.available_until

    # ---- workflow ------------------------------------------------------------
    def _move_to(self, new_status, changed_by, note=""):
        if new_status not in ALLOWED_TRANSITIONS[self._status]:
            raise InvalidStatusTransitionError(
                f"Donation {self.donation_id} is {self._status.value} and cannot be "
                f"changed to {new_status.value}.")
        self._status = new_status
        self._history.append(StatusChange(new_status, changed_by, note=note))

    def _require_volunteer(self, user):
        if not user.can_handle_delivery():
            raise PermissionDeniedError("Only volunteers can do this.")

    def _require_assigned(self, volunteer):
        self._require_volunteer(volunteer)
        if self._volunteer_id != volunteer.user_id:
            raise PermissionDeniedError(
                f"Donation {self.donation_id} is assigned to "
                f"{self._volunteer_id or 'no volunteer'}, not {volunteer.user_id}.")

    def claim(self, volunteer, now=None):
        self._require_volunteer(volunteer)
        if self._status is DonationStatus.CLAIMED:
            raise InvalidStatusTransitionError(
                f"Donation {self.donation_id} is already claimed by {self._volunteer_id}.")
        if self._status is DonationStatus.AVAILABLE and self.is_past_expiry(now):
            raise InvalidStatusTransitionError(f"Donation {self.donation_id} has expired.")
        self._move_to(DonationStatus.CLAIMED, volunteer.user_id, "Claimed by volunteer")
        self._volunteer_id = volunteer.user_id

    def release(self, volunteer):
        """The volunteer can no longer pick it up; make it available again."""
        self._require_assigned(volunteer)
        self._move_to(DonationStatus.AVAILABLE, volunteer.user_id, "Released by volunteer")
        self._volunteer_id = None

    def mark_picked_up(self, volunteer):
        self._require_assigned(volunteer)
        self._move_to(DonationStatus.PICKED_UP, volunteer.user_id, "Food collected from donor")

    def mark_delivered(self, volunteer):
        self._require_assigned(volunteer)
        self._move_to(DonationStatus.DELIVERED, volunteer.user_id, "Food delivered")

    def cancel(self, donor):
        if donor.user_id != self._donor_id:
            raise PermissionDeniedError("Only the donor who created this donation can cancel it.")
        self._move_to(DonationStatus.CANCELLED, donor.user_id, "Cancelled by donor")

    def expire_if_due(self, now=None):
        """Mark food that was not collected in time as Expired. Returns True if changed."""
        if (self._status in (DonationStatus.AVAILABLE, DonationStatus.CLAIMED)
                and self.is_past_expiry(now)):
            self._move_to(DonationStatus.EXPIRED, "SYSTEM", "Not collected before the available-until time")
            return True
        return False

    # ---- conversion ------------------------------------------------------------
    def to_dict(self):
        return {
            "donation_id": self.donation_id,
            "donor_id": self.donor_id,
            "food_name": self.food_name,
            "quantity": self.quantity,
            "unit": self.unit,
            "location": self.location,
            "location_details": self.location_details,
            "available_until": self.available_until.isoformat(),
            "contact_name": self.contact_name,
            "contact_phone": self.contact_phone,
            "notes": self.notes,
            "status": self.status.value,
            "volunteer_id": self.volunteer_id,
            "created_at": self.created_at.isoformat(),
            "history": [change.to_dict() for change in self._history],
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValidationError("Donation record must be a JSON object.")
        try:
            return cls(
                donation_id=data["donation_id"],
                donor_id=data["donor_id"],
                food_name=data["food_name"],
                quantity=f"{data['quantity']} {data.get('unit', '')}",
                location=data["location"],
                available_until=_parse_iso(data["available_until"], "available_until"),
                contact_name=data["contact_name"],
                contact_phone=data["contact_phone"],
                notes=data.get("notes", ""),
                location_details=data.get("location_details"),
                status=DonationStatus(data["status"]),
                volunteer_id=data.get("volunteer_id"),
                created_at=_parse_iso(data["created_at"], "created_at"),
                history=[StatusChange.from_dict(h) for h in data.get("history", [])],
            )
        except KeyError as missing:
            raise ValidationError(f"Donation record is missing {missing}.") from None
        except ValueError as error:  # unknown status value
            raise ValidationError(f"Invalid donation record: {error}") from None

"""Validation and parsing rules, shared by the models, services and the CLI."""
import re
from datetime import datetime, timedelta
 
from .exceptions import ValidationError
 
MAX_DAYS_AHEAD = 7
MAX_QUANTITY = 10000
DEFAULT_UNIT = "Meals"
 
_NAME_CHARS = re.compile(r"[^\W\d_][\w .'&()/,\-]*")
_QUANTITY = re.compile(r"(\d+(?:\.\d+)?)\s*([^\W\d_][^\W\d]*)?")
 
 
def clean(value):
    """Trim and collapse repeated spaces."""
    return " ".join(str(value).split()) if value is not None else ""
 
 
def capitalize_words(text):
    """'chennai' -> 'Chennai', 'anna nagar, chennai' -> 'Anna Nagar, Chennai'.
    Words the user already capitalised (e.g. 'IIT', 'McDonald') are kept as typed."""
    return " ".join(word[:1].upper() + word[1:] if word.islower() else word
                    for word in text.split(" "))
 
 
def validate_text(value, field, min_len=2, max_len=60):
    text = clean(value)
    if not text:
        raise ValidationError(f"{field} cannot be empty.")
    if not min_len <= len(text) <= max_len:
        raise ValidationError(f"{field} must be {min_len}-{max_len} characters long.")
    if not _NAME_CHARS.fullmatch(text):
        raise ValidationError(f"{field} must start with a letter and contain only letters, "
                              "numbers, spaces and . ' & ( ) / , -")
    return capitalize_words(text)
 
 
def validate_person_name(value):
    name = validate_text(value, "Name")
    if any(ch.isdigit() for ch in name):
        raise ValidationError("Name cannot contain numbers.")
    return name
 
 
def validate_food_name(value):
    return validate_text(value, "Food name")
 
 
def validate_location(value):
    return validate_text(value, "Location", max_len=100)
 
 
def validate_phone(value):
    """Indian mobile number: 10 digits starting 6-9, optional +91 / 0 prefix.
    Returns the 10 digits, e.g. '9876543210'."""
    digits = re.sub(r"[\s\-()]", "", clean(value))
    if not digits:
        raise ValidationError("Contact number cannot be empty.")
    if digits.startswith("+91"):
        digits = digits[3:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if not (digits.isdigit() and len(digits) == 10 and digits[0] in "6789"):
        raise ValidationError("Enter a valid 10-digit mobile number, e.g. 9876543210.")
    return digits
 
 
def parse_quantity(value):
    """'20 Meals' -> (20, 'Meals'); '20' -> (20, 'Meals'); '2.5 kg' -> (2.5, 'Kg')."""
    text = clean(value)
    if not text:
        raise ValidationError("Quantity cannot be empty.")
    match = _QUANTITY.fullmatch(text)
    if not match:
        raise ValidationError("Enter quantity as a number and unit, e.g. 20 Meals or 5 kg.")
    amount = float(match.group(1))
    if amount <= 0:
        raise ValidationError("Quantity must be greater than zero.")
    if amount > MAX_QUANTITY:
        raise ValidationError(f"Quantity cannot be more than {MAX_QUANTITY}.")
    unit = clean(match.group(2) or DEFAULT_UNIT).title()
    if len(unit) > 20:
        raise ValidationError("Unit name is too long.")
    return (int(amount) if amount.is_integer() else amount), unit
 
 
_TIME_FORMATS = ("%I:%M %p", "%I %p", "%H:%M")
_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y")
 
 
def _parse_time(text):
    text = re.sub(r"(?i)(\d)\s*([ap])\.?\s*m\.?$", r"\1 \2M", text)  # 8pm, 8 p.m. -> 8 PM
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text.upper(), fmt).time()
        except ValueError:
            continue
    return None
 
 
def parse_available_until(value, now=None):
    """Accepts '8:00 PM', '8 PM', '20:00', 'tomorrow 9 AM', '2026-10-26 8:00 PM'.
    A time without a date means today. The result must be in the future and
    no more than MAX_DAYS_AHEAD days away."""
    now = now or datetime.now()
    text = clean(value)
    if not text:
        raise ValidationError("Available-until time cannot be empty.")
 
    day = now.date()
    lowered = text.lower()
    if lowered.startswith(("today", "tomorrow")):
        word, _, rest = text.partition(" ")
        if word.lower() == "tomorrow":
            day = day + timedelta(days=1)
        text = rest.strip()
    else:
        first, _, rest = text.partition(" ")
        for fmt in _DATE_FORMATS:
            try:
                day = datetime.strptime(first, fmt).date()
                text = rest.strip()
                break
            except ValueError:
                continue
 
    time_of_day = _parse_time(text) if text else None
    if time_of_day is None:
        raise ValidationError("Enter a time like 8:00 PM or 20:00 "
                              "(optionally 'tomorrow 9 AM' or '2026-10-26 8:00 PM').")
 
    moment = datetime.combine(day, time_of_day)
    if moment <= now:
        raise ValidationError("Available-until time must be in the future. "
                              "For tomorrow, type e.g. 'tomorrow 9 AM'.")
    if moment > now + timedelta(days=MAX_DAYS_AHEAD):
        raise ValidationError(f"Available-until time cannot be more than {MAX_DAYS_AHEAD} days ahead.")
    return moment
 
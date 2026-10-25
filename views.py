"""Plain-text formatting of results. Kept separate from the workflow so the
final app can replace it with web pages or JSON responses."""
from datetime import datetime, timedelta

from .models import format_phone


def _title(text):
    return [text, "-" * len(text)]


def format_time(moment, now=None):
    """'8:00 PM' today, 'Tomorrow, 9:00 AM', otherwise '28 Oct 2026, 8:00 PM'."""
    now = now or datetime.now()
    clock = moment.strftime("%I:%M %p").lstrip("0")
    if moment.date() == now.date():
        return clock
    if moment.date() == now.date() + timedelta(days=1):
        return f"Tomorrow, {clock}"
    return f"{moment.day} {moment.strftime('%b %Y')}, {clock}"


def donation_created(donation):
    return "\n".join([
        "Donation Created Successfully.",
        f"Donation ID: {donation.donation_id}",
        f"Status: {donation.status.value}",
    ])


def donation_card(donation):
    return "\n".join([
        donation.donation_id,
        f"Food : {donation.food_name}",
        f"Quantity : {donation.quantity_text}",
        f"Location : {donation.location}",
        f"Status : {donation.status.value}",
    ])


def available_donations(donations):
    lines = _title("Available Donations")
    if not donations:
        lines.append("No donations are available right now.")
        return "\n".join(lines)
    return "\n".join(lines) + "\n" + "\n\n".join(donation_card(d) for d in donations)


def status_update(donation):
    lines = [f"Donation {donation.donation_id}", f"Status: {donation.status.value}"]
    if donation.volunteer_id:
        lines.append(f"Volunteer: {donation.volunteer_id}")
    return "\n".join(lines)


def donation_details(donation, donor=None, volunteer=None, now=None):
    lines = _title(f"Donation {donation.donation_id}")
    lines += [
        f"Food : {donation.food_name}",
        f"Quantity : {donation.quantity_text}",
        f"Location : {donation.location}",
    ]
    if donation.location_details:
        d = donation.location_details
        lines.append(f"Map : {d['latitude']}, {d['longitude']} ({d['name']}, {d['country']})")
    lines += [
        f"Available Until : {format_time(donation.available_until, now)}",
        f"Contact : {donation.contact_name}, {format_phone(donation.contact_phone)}",
        f"Donor : {donor if donor else donation.donor_id}",
        f"Status : {donation.status.value}",
        f"Volunteer : {volunteer if volunteer else (donation.volunteer_id or '-')}",
    ]
    if donation.notes:
        lines.append(f"Notes : {donation.notes}")
    lines += ["", "Status History"]
    for change in donation.history:
        when = change.at.strftime("%d %b %Y %I:%M %p")
        lines.append(f"  {when} - {change.status.value} ({change.changed_by}) {change.note}".rstrip())
    return "\n".join(lines)


def donation_table(donations, now=None):
    if not donations:
        return "No donations found."
    rows = [(d.donation_id, d.food_name, d.quantity_text, d.location,
             format_time(d.available_until, now), d.status.value, d.volunteer_id or "-")
            for d in donations]
    headers = ("ID", "Food", "Quantity", "Location", "Until", "Status", "Volunteer")
    widths = [max(len(str(r[i])) for r in rows + [headers]) for i in range(len(headers))]
    line = lambda r: "  ".join(str(v).ljust(w) for v, w in zip(r, widths)).rstrip()
    return "\n".join([line(headers), "-" * len(line(headers))] + [line(r) for r in rows])


def user_table(users):
    if not users:
        return "No users registered."
    rows = [(u.user_id, u.role.value, u.name, format_phone(u.phone), u.location) for u in users]
    headers = ("ID", "Role", "Name", "Phone", "Location")
    widths = [max(len(r[i]) for r in rows + [headers]) for i in range(len(headers))]
    line = lambda r: "  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip()
    return "\n".join([line(headers), "-" * len(line(headers))] + [line(r) for r in rows])


def status_summary(counts):
    lines = _title("Donation Summary")
    lines += [f"{status.value} : {count}" for status, count in counts.items()]
    lines.append(f"Total : {sum(counts.values())}")
    return "\n".join(lines)

# Food Donation Management System — Backend Prototype

A working backend prototype of the core donation workflow for the final
internship project. Donors post surplus food, volunteers see what is
available, claim it, pick it up and deliver it, and every step is recorded.
The console front end is deliberately thin: all rules live in the
`food_donation` package so a web or mobile app can reuse them later.

## Requirements
- Python 3.8 or later
- No external libraries (the location API uses Python's built-in `urllib`)
- Internet is optional; it is only used to verify pickup locations

## Run
```bash
python main.py
```
Run the automated tests:
```bash
python -m unittest -v
```

## Sample users (in `data/users.json`)
| ID | Role | Name |
|---|---|---|
| DNR001 | Donor | Ravi Kumar |
| VOL101 | Volunteer | Priya |
| VOL102 | Volunteer | Arun |
| REQ001 | Requester | Hope Shelter |

New users can be registered from the main menu. IDs are generated automatically
(donors `DNR001…`, volunteers `VOL101…`, requesters `REQ001…`, donations `DON001…`).

## Walkthrough (matches the expected output)
Log in as `DNR001` → **Create Donation**:
```text
Create Donation
Food Name: Vegetable Rice
Quantity: 20 Meals
Location: Chennai
Available Until: 8:00 PM
Contact Number [98765 43210]:

Donation Created Successfully.
Donation ID: DON001
Status: Available
Location verified: Chennai, Tamil Nadu, India
```
Log out, log in as `VOL102` → **View Available Donations**:
```text
Available Donations
-------------------
DON001
Food : Vegetable Rice
Quantity : 20 Meals
Location : Chennai
Status : Available
```
**Claim Donation** → `DON001`:
```text
Donation DON001
Status: Claimed
Volunteer: VOL102
Pickup contact: Ravi Kumar, 98765 43210
```
Then **Mark Picked Up** and **Mark Delivered** move it to `Picked Up` and
`Delivered`. **Track Donation** on the main menu shows the full status history.

"Available Until" must be a future time. A time on its own means today, so if
8:00 PM has already passed, enter a later time or e.g. `tomorrow 9 AM`.

## Donation workflow
```
Available ──claim──▶ Claimed ──pick up──▶ Picked Up ──deliver──▶ Delivered
    ▲                   │
    └─────release───────┘
Available / Claimed ──▶ Cancelled (by the donor)
Available / Claimed ──▶ Expired   (automatically, after the available-until time)
```
Allowed moves are defined in one table (`ALLOWED_TRANSITIONS` in `models.py`);
any other move raises `InvalidStatusTransitionError`.

## Project structure
```
food_donation_system/
├── main.py                  # console front end (menus only)
├── data/
│   ├── users.json           # user records
│   └── donations.json       # donation records with status history
├── food_donation/
│   ├── models.py            # User → Donor / Volunteer / Requester, Donation, DonationStatus
│   ├── services.py          # UserService, DonationService (the workflow)
│   ├── storage.py           # JsonFile, Repository → UserRepository / DonationRepository
│   ├── location_service.py  # Open-Meteo Geocoding API client
│   ├── validators.py        # input rules and parsing
│   ├── views.py             # text output formatting
│   └── exceptions.py        # custom exception hierarchy
└── tests/
    └── test_workflow.py     # 19 automated tests
```

## How the topics are covered
- **OOP:** `Donor`, `Volunteer` and `Requester` inherit from `User` and override
  permission methods (`can_create_donation`, `can_handle_delivery`). Repositories
  share a `Repository` base class. Attributes are validated through properties,
  and a donation's status can only change through its workflow methods.
- **Data structures:** an `Enum` for statuses and roles, a transition table
  (dict of sets), dictionaries keyed by ID for fast lookup, and a list of
  `StatusChange` objects for history.
- **File handling:** JSON storage with atomic saves; corrupt files are backed up
  to `.bak` before anything is overwritten.
- **API integration:** the pickup location is checked with the free
  [Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api)
  (no key needed). Coordinates are stored for future map and nearest-donation
  features. If the API is down, offline or finds nothing, the donation is still
  saved and a note is shown.
- **Exception handling:** every invalid operation raises a specific error that
  the menu reports without crashing (see below). If saving fails, the change is
  rolled back.

## Invalid operations handled
| Situation | Result |
|---|---|
| Blank or invalid food name, quantity, location, phone or time | Explains the rule and asks again |
| Time in the past or more than 7 days ahead | Rejected |
| Unknown user or donation ID | `No donation found with ID 'DON009'.` |
| Volunteer creates a donation / donor claims one | `PermissionDeniedError` |
| Claiming a donation that is already claimed | `Donation DON001 is already claimed by VOL101.` |
| Another volunteer marks it picked up or delivered | `Donation DON001 is assigned to VOL101, not VOL102.` |
| Skipping a step (Claimed → Delivered) | `InvalidStatusTransitionError` |
| Claiming a cancelled, expired or delivered donation | `InvalidStatusTransitionError` |
| Cancelling someone else's donation | `PermissionDeniedError` |
| Corrupt data file / save failure | Backup made / change rolled back |
| Location API offline, unavailable or bad response | Donation saved; note shown |

## Ready for the final app
- The **Requester** role exists and can view available donations; food requests
  can be added in the final app without changing the donation workflow.
- Services take plain values and return objects, so they can sit behind a REST
  API (Flask/FastAPI) unchanged.
- `JsonFile` and the repositories can be swapped for a database.
- Stored coordinates allow "donations near me" sorting later.

"""Automated checks for the donation workflow. Run:  python -m unittest -v"""
import io
import json
import socket
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
 
from food_donation.exceptions import (
    DonationNotFoundError,
    DuplicateUserError,
    InvalidStatusTransitionError,
    LocationNotFoundError,
    NetworkError,
    PermissionDeniedError,
    StorageError,
    UserNotFoundError,
    ValidationError,
)
from food_donation.location_service import LocationService
from food_donation.models import DonationStatus
from food_donation.services import DonationService, UserService
from food_donation.storage import DonationRepository, UserRepository
from food_donation.validators import (
    parse_available_until,
    parse_quantity,
    validate_location,
    validate_phone,
)
 
NOW = datetime(2026, 10, 25, 12, 0)
 
 
class FakeLocationService:
    def __init__(self, error=None):
        self.error = error
 
    def verify(self, location):
        if self.error:
            raise self.error
        return {"name": "Chennai", "state": "Tamil Nadu", "country": "India",
                "latitude": 13.0878, "longitude": 80.2785}
 
 
class Clock:
    def __init__(self, now):
        self.now = now
 
    def __call__(self):
        return self.now
 
 
class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clock = Clock(NOW)
        self.build()
        self.donor = self.users.register("Donor", "Ravi Kumar", "9876543210", "Chennai")
        self.vol1 = self.users.register("Volunteer", "Priya", "9123456780", "Chennai")
        self.vol2 = self.users.register("Volunteer", "Arun", "9988776655", "Chennai")
 
    def tearDown(self):
        self.tmp.cleanup()
 
    def build(self, location_service=None):
        user_repo = UserRepository(self.dir / "users.json")
        donation_repo = DonationRepository(self.dir / "donations.json")
        user_repo.load()
        donation_repo.load()
        self.users = UserService(user_repo)
        self.service = DonationService(donation_repo, self.users,
                                       location_service or FakeLocationService(), self.clock)
 
    def create(self, until="8:00 PM"):
        donation, _ = self.service.create_donation(
            self.donor.user_id, "Vegetable Rice", "20 Meals", "Chennai", until)
        return donation
 
    # ---- happy path ------------------------------------------------------------
    def test_ids_follow_expected_pattern(self):
        self.assertEqual(self.donor.user_id, "DNR001")
        self.assertEqual((self.vol1.user_id, self.vol2.user_id), ("VOL101", "VOL102"))
        self.assertEqual(self.create().donation_id, "DON001")
        self.assertEqual(self.create().donation_id, "DON002")
 
    def test_full_lifecycle(self):
        d = self.create()
        self.assertEqual(d.status, DonationStatus.AVAILABLE)
        self.assertEqual(d.quantity_text, "20 Meals")
        self.assertEqual(d.available_until, datetime(2026, 10, 25, 20, 0))
        self.assertTrue(d.location_verified)
        self.assertIn(d, self.service.available_donations())
 
        self.service.claim("don001", "VOL102")
        self.assertEqual((d.status, d.volunteer_id), (DonationStatus.CLAIMED, "VOL102"))
        self.assertNotIn(d, self.service.available_donations())
 
        self.service.mark_picked_up("DON001", "VOL102")
        self.service.mark_delivered("DON001", "VOL102")
        self.assertEqual(d.status, DonationStatus.DELIVERED)
        self.assertEqual([h.status.value for h in d.history],
                         ["Available", "Claimed", "Picked Up", "Delivered"])
 
    def test_records_survive_restart(self):
        self.create()
        self.service.claim("DON001", "VOL102")
        self.build()
        d = self.service.get("DON001")
        self.assertEqual((d.status, d.volunteer_id), (DonationStatus.CLAIMED, "VOL102"))
        self.assertEqual(len(d.history), 2)
        self.assertEqual(self.users.get("vol102").name, "Arun")
 
    def test_release_makes_donation_available_again(self):
        self.create()
        self.service.claim("DON001", "VOL101")
        d = self.service.release("DON001", "VOL101")
        self.assertEqual((d.status, d.volunteer_id), (DonationStatus.AVAILABLE, None))
        self.service.claim("DON001", "VOL102")
 
    # ---- invalid operations ------------------------------------------------------
    def test_double_claim_rejected(self):
        self.create()
        self.service.claim("DON001", "VOL101")
        with self.assertRaises(InvalidStatusTransitionError):
            self.service.claim("DON001", "VOL102")
 
    def test_only_assigned_volunteer_can_progress(self):
        self.create()
        self.service.claim("DON001", "VOL101")
        with self.assertRaises(PermissionDeniedError):
            self.service.mark_picked_up("DON001", "VOL102")
 
    def test_steps_cannot_be_skipped_or_reversed(self):
        self.create()
        with self.assertRaises(PermissionDeniedError):  # not claimed by anyone yet
            self.service.mark_delivered("DON001", "VOL101")
        self.service.claim("DON001", "VOL101")
        with self.assertRaises(InvalidStatusTransitionError):
            self.service.mark_delivered("DON001", "VOL101")
        self.service.mark_picked_up("DON001", "VOL101")
        self.service.mark_delivered("DON001", "VOL101")
        with self.assertRaises(InvalidStatusTransitionError):
            self.service.release("DON001", "VOL101")
 
    def test_roles_are_enforced(self):
        self.create()
        with self.assertRaises(PermissionDeniedError):
            self.service.create_donation("VOL101", "Rice", "5", "Chennai", "8 PM")
        with self.assertRaises(PermissionDeniedError):
            self.service.claim("DON001", "DNR001")
        other = self.users.register("Donor", "Meena", "9000000001", "Chennai")
        with self.assertRaises(PermissionDeniedError):
            self.service.cancel("DON001", other.user_id)
 
    def test_cancel_then_claim_rejected(self):
        self.create()
        self.service.cancel("DON001", "DNR001")
        with self.assertRaises(InvalidStatusTransitionError):
            self.service.claim("DON001", "VOL101")
 
    def test_duplicate_phone_rejected(self):
        with self.assertRaises(DuplicateUserError):
            self.users.register("Donor", "Paul", "+91 98765 43210", "Chennai")
        self.assertEqual(len(self.users.all()), 3)
 
    def test_unknown_ids(self):
        with self.assertRaises(DonationNotFoundError):
            self.service.claim("DON999", "VOL101")
        with self.assertRaises(UserNotFoundError):
            self.users.get("VOL999")
 
    def test_expired_donations_leave_available_list(self):
        self.create("1:00 PM")
        self.clock.now = NOW + timedelta(hours=2)
        self.assertEqual(self.service.available_donations(), [])
        self.assertEqual(self.service.get("DON001").status, DonationStatus.EXPIRED)
        with self.assertRaises(InvalidStatusTransitionError):
            self.service.claim("DON001", "VOL101")
 
    def test_failed_save_rolls_back(self):
        self.create()
        with mock.patch.object(self.service.donations, "save", side_effect=StorageError("disk full")):
            with self.assertRaises(StorageError):
                self.service.claim("DON001", "VOL101")
        self.assertEqual(self.service.get("DON001").status, DonationStatus.AVAILABLE)
 
    def test_corrupt_file_is_backed_up(self):
        (self.dir / "donations.json").write_text("{oops")
        with self.assertRaises(StorageError):
            DonationRepository(self.dir / "donations.json").load()
        self.assertTrue((self.dir / "donations.json.bak").exists())
 
    # ---- API failures never block a donation ------------------------------------
    def test_location_api_failures_are_not_fatal(self):
        for error in (NetworkError("offline"), LocationNotFoundError("nope")):
            self.build(FakeLocationService(error))
            donation, note = self.service.create_donation("DNR001", "Idli", "30", "Chennai", "9 PM")
            self.assertFalse(donation.location_verified)
            self.assertTrue(note.startswith("Note:"))
 
 
class ValidationTests(unittest.TestCase):
    def test_quantity(self):
        self.assertEqual(parse_quantity("20 meals"), (20, "Meals"))
        self.assertEqual(parse_quantity("20"), (20, "Meals"))
        self.assertEqual(parse_quantity("2.5 kg"), (2.5, "Kg"))
        for bad in ("", "0 meals", "-5", "meals", "abc 20"):
            with self.assertRaises(ValidationError):
                parse_quantity(bad)
 
    def test_available_until(self):
        self.assertEqual(parse_available_until("8:00 PM", NOW), datetime(2026, 10, 25, 20, 0))
        self.assertEqual(parse_available_until("8pm", NOW), datetime(2026, 10, 25, 20, 0))
        self.assertEqual(parse_available_until("20:00", NOW), datetime(2026, 10, 25, 20, 0))
        self.assertEqual(parse_available_until("tomorrow 9 AM", NOW), datetime(2026, 10, 26, 9, 0))
        self.assertEqual(parse_available_until("2026-10-27 8:00 PM", NOW), datetime(2026, 10, 27, 20, 0))
        for bad in ("", "9:00 AM", "25:00", "soon", "2026-12-30 8 PM"):
            with self.assertRaises(ValidationError):
                parse_available_until(bad, NOW)
 
    def test_capitalisation(self):
        self.assertEqual(validate_location("chennai"), "Chennai")
        self.assertEqual(validate_location("anna  nagar, chennai"), "Anna Nagar, Chennai")
        self.assertEqual(validate_location("IIT Madras"), "IIT Madras")
 
    def test_phone(self):
        self.assertEqual(validate_phone("+91 98765 43210"), "9876543210")
        for bad in ("12345", "1234567890", "phone"):
            with self.assertRaises(ValidationError):
                validate_phone(bad)
 
 
class _Resp(io.BytesIO):
    def __enter__(self):
        return self
 
    def __exit__(self, *args):
        pass
 
 
class LocationServiceTests(unittest.TestCase):
    def run_with(self, effect):
        with mock.patch("urllib.request.urlopen", side_effect=effect):
            return LocationService().verify("Anna Nagar, Chennai")
 
    def test_success_falls_back_to_city(self):
        calls = []
 
        def fake(request, timeout):
            calls.append(request.full_url)
            body = {} if len(calls) == 1 else {"results": [
                {"name": "Chennai", "admin1": "Tamil Nadu", "country": "India",
                 "latitude": 13.08784, "longitude": 80.27847}]}
            return _Resp(json.dumps(body).encode())
        result = self.run_with(fake)
        self.assertEqual((result["name"], result["latitude"]), ("Chennai", 13.0878))
        self.assertEqual(len(calls), 2)
 
    def test_failures(self):
        def network(*a, **k):
            raise urllib.error.URLError(socket.gaierror("no internet"))
        with self.assertRaises(NetworkError):
            self.run_with(network)
        with self.assertRaises(LocationNotFoundError):
            self.run_with(lambda *a, **k: _Resp(b"{}"))
 
 
if __name__ == "__main__":
    unittest.main()
 

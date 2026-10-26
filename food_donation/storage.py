"""JSON persistence. JsonFile handles the file itself; repositories turn
records into User/Donation objects and generate IDs."""
import json
import os
import re
import shutil
from pathlib import Path

from .exceptions import StorageError, ValidationError
from .models import Donation, User


class JsonFile:
    """Reads and writes one JSON list safely (atomic save, backup on corruption)."""

    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if not self.path.exists():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise StorageError(f"Could not read {self.path.name}: {error}") from error
        if not text.strip():
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise StorageError(f"{self.path.name} is not valid JSON (line {error.lineno}). "
                               + self.backup()) from error
        if not isinstance(data, list):
            raise StorageError(f"{self.path.name} must contain a JSON list. " + self.backup())
        return data

    def write(self, records):
        temp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temp.open("w", encoding="utf-8") as file:
                json.dump(records, file, indent=4, ensure_ascii=False)
            os.replace(temp, self.path)
        except OSError as error:
            try:
                temp.unlink()
            except OSError:
                pass
            raise StorageError(f"Could not save {self.path.name}: {error}") from error

    def backup(self):
        backup = self.path.with_name(self.path.name + ".bak")
        try:
            shutil.copy2(self.path, backup)
            return f"A copy was saved as {backup.name}."
        except OSError:
            return "A backup copy could not be made."


class Repository:
    """Base class: keeps records in memory by ID and saves them as JSON."""

    model = None
    id_field = None

    def __init__(self, path):
        self._file = JsonFile(path)
        self._items = {}

    def load(self):
        """Load records; invalid or duplicate ones are skipped. Returns warnings."""
        self._items.clear()
        warnings = []
        for number, record in enumerate(self._file.read(), start=1):
            try:
                item = self.model.from_dict(record)
            except ValidationError as error:
                warnings.append(f"{self._file.path.name} record {number} skipped: {error}")
                continue
            key = self._key(getattr(item, self.id_field))
            if key in self._items:
                warnings.append(f"{self._file.path.name} record {number} skipped: duplicate ID.")
                continue
            self._items[key] = item
        if warnings:
            warnings.append(self._file.backup())
        return warnings

    def save(self):
        self._file.write([item.to_dict() for item in self._items.values()])

    @staticmethod
    def _key(item_id):
        return str(item_id).strip().upper()

    def get(self, item_id):
        return self._items.get(self._key(item_id))

    def add(self, item):
        self._items[self._key(getattr(item, self.id_field))] = item

    def replace(self, item):
        self.add(item)

    def remove(self, item_id):
        self._items.pop(self._key(item_id), None)

    def all(self):
        return list(self._items.values())

    def __len__(self):
        return len(self._items)

    def next_id(self, prefix, start=1, width=3):
        pattern = re.compile(rf"{re.escape(prefix)}(\d+)$")
        numbers = []
        for key in self._items:
            match = pattern.match(key)
            if match:
                numbers.append(int(match.group(1)))
        return f"{prefix}{max(numbers) + 1 if numbers else start:0{width}d}"


class UserRepository(Repository):
    model = User
    id_field = "user_id"


class DonationRepository(Repository):
    model = Donation
    id_field = "donation_id"

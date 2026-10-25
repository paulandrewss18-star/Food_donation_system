"""Exception hierarchy. Catching FoodDonationError handles every expected problem."""
 
 
class FoodDonationError(Exception):
    """Base class for all expected errors in the system."""
 
 
class ValidationError(FoodDonationError):
    """A value breaks an input rule (blank name, bad phone, past expiry time...)."""
 
 
class DuplicateUserError(FoodDonationError):
    """A user with the same phone number is already registered."""
 
 
class NotFoundError(FoodDonationError):
    """Base class for lookups that find nothing."""
 
 
class UserNotFoundError(NotFoundError):
    pass
 
 
class DonationNotFoundError(NotFoundError):
    pass
 
 
class PermissionDeniedError(FoodDonationError):
    """The user's role or ownership does not allow this action."""
 
 
class InvalidStatusTransitionError(FoodDonationError):
    """The donation cannot move to the requested status (e.g. Delivered -> Claimed)."""
 
 
class StorageError(FoodDonationError):
    """A data file could not be read, parsed, or written."""
 
 
# ---- external API (location verification) -----------------------------------
 
class LocationServiceError(FoodDonationError):
    """Base class for problems with the geocoding API."""
 
 
class LocationNotFoundError(LocationServiceError):
    """The API found no place with that name."""
 
 
class NetworkError(LocationServiceError):
    """No internet connection, DNS failure, or timeout."""
 
 
class APIUnavailableError(LocationServiceError):
    """The API answered with a server error or rate limit."""
 
 
class InvalidAPIResponseError(LocationServiceError):
    """The API answered with data in an unexpected format."""
 
"""Core backend for the Food Donation Management System prototype.

Layers (each module has one job):
  models            - User roles and the Donation with its status workflow
  validators        - input rules shared by every layer
  storage           - JSON repositories for users and donations
  location_service  - public geocoding API used to verify pickup locations
  services          - the business workflow (create, claim, pick up, deliver...)
  views             - plain-text formatting of results
"""

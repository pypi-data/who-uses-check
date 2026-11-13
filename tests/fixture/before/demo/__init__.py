import requests


def get_session():
    return requests.Session()


def merge_environment_settings():
    """Removed in the fixture's 'after' version, to exercise the lookup."""

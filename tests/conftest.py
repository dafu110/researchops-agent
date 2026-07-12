import os


# API smoke tests exercise the explicit local-demo profile. Production defaults
# remain fail-closed and are covered by test_nonlocal_deployment_rejects_unconfigured_authentication.
os.environ["APP_ENV"] = "test"
os.environ["AUTH_REQUIRED"] = "false"

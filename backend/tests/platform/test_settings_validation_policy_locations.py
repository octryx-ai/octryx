"""Nested and source failures are reported only as far as the settings model declares the location, unknown internal failures are not converted, and declared locations cover field names and environment aliases."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import Settings
from app.settings_validation_policy import (
    REDACTED_LOCATION_PART,
    SettingsFieldError,
    SettingsValidationError,
    declared_locations,
    load_validated_settings,
)
from tests.platform.settings_validation_policy_support import (  # noqa: F401
    MARKERS,
    _operator_surfaces,
    settings_environment,
)


class _ProbeBlock(BaseModel):
    ceiling: int = 1


class _NestedProbeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OE824_PROBE_", env_nested_delimiter="__", env_file=None)

    block: _ProbeBlock = _ProbeBlock()
    ceilings: dict[str, int] = {}


@pytest.mark.parametrize(
    ("variable", "value", "location"),
    [
        pytest.param(
            "OE824_PROBE_BLOCK__CEILING",
            MARKERS["nested_ceiling"],
            "block.ceiling",
            id="nested field",
        ),
        pytest.param(
            "OE824_PROBE_CEILINGS",
            f'{{"{MARKERS["nested_key"]}": "no"}}',
            f"ceilings.{REDACTED_LOCATION_PART}",
            id="operator-supplied mapping key",
        ),
    ],
)
def test_a_nested_location_is_reported_only_as_far_as_the_model_declares_it(
    settings_environment: pytest.MonkeyPatch,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    variable: str,
    value: str,
    location: str,
) -> None:
    settings_environment.setenv(variable, value)

    with pytest.raises(SettingsValidationError) as failure:
        load_validated_settings(_NestedProbeSettings)

    error = failure.value
    surfaces = _operator_surfaces(error, caplog)
    for marker in MARKERS.values():
        assert marker not in surfaces
    assert [fault.location for fault in error.faults] == [location]
    assert error.faults[0].reason == "int_parsing"


def test_a_settings_source_failure_is_reported_by_field_without_its_value(
    settings_environment: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture  # noqa: F811
) -> None:
    settings_environment.setenv("OE824_PROBE_CEILINGS", MARKERS["source_value"])

    with pytest.raises(SettingsValidationError) as failure:
        load_validated_settings(_NestedProbeSettings)

    surfaces = _operator_surfaces(failure.value, caplog)
    assert MARKERS["source_value"] not in surfaces
    assert failure.value.safe_field_reasons == (("ceilings", "settings_source_error"),)


def test_an_unknown_internal_failure_is_not_converted_into_a_settings_failure() -> None:
    class _BrokenSettings(BaseSettings):
        model_config = SettingsConfigDict(env_file=None)

        @staticmethod
        def _fault() -> None:
            raise RuntimeError("settings validator defect")

        def model_post_init(self, _context: object) -> None:
            self._fault()

    with pytest.raises(RuntimeError) as failure:
        load_validated_settings(_BrokenSettings)

    assert not isinstance(failure.value, SettingsValidationError)
    assert str(failure.value) == "settings validator defect"


def test_a_field_rejection_names_its_settings_without_a_value() -> None:
    rejection = SettingsFieldError("example_reason", "Do the documented thing.", ("jwt_secret", "encryption_key"))

    assert str(rejection) == "Do the documented thing. Affected settings: jwt_secret, encryption_key."
    assert rejection.reason == "example_reason"
    assert rejection.fields == ("jwt_secret", "encryption_key")


def test_declared_locations_cover_field_names_and_their_environment_aliases() -> None:
    declared = declared_locations(Settings)

    assert {"jwt_secret", "trusted_proxy_ips", "max_multipart_request_bytes"} <= declared
    assert "OCTRYX_TRUSTED_PROXY_IPS" in declared
    assert "OCTRYX_RUNTIME_PROFILE" in declared

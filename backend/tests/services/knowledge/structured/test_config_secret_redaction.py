"""Secret settings in configuration files lose their values in the structured graph and in the searchable text;
source code keeps its ``password=`` assignments."""

from __future__ import annotations

import pytest

from app.services.knowledge.code.redaction import is_config_path, redact_repository_text
from app.services.knowledge.structured.config_files import is_secret, parse_ini, parse_properties, parse_yaml
from app.services.redaction_policy import (
    has_embedded_credentials,
    is_secret_setting_key,
    looks_like_secret_value,
    redact_embedded_credentials,
    redact_secret_text,
)

PROBES = {
    "KeystorePass": "changeit",
    "Pwd": "abc",
    "Passwort": "geheim",
    "Kennwort": "geheim2",
    "db_passwd": "pw1",
    "admin-pin": "1234",
    "clientSecret": "cs-1",
    "AUTH_TOKEN": "tok-1",
    "ApiKey": "k-1",
    "api-key": "k-2",
    "ServiceCredentials": "cred-1",
}
ORACLE = "jdbc:oracle:thin:scott/tiger@db:1521/X"


@pytest.mark.parametrize("key", sorted(PROBES))
def test_secret_setting_names_are_judged_by_their_last_word(key):
    assert is_secret_setting_key(key)
    assert is_secret(key, PROBES[key])


@pytest.mark.parametrize("key", ["Timeout", "PinCount", "TokenTimeout", "Bypass", "Compass", "MaxTokens", "Path"])
def test_ordinary_setting_names_keep_their_values(key):
    assert not is_secret_setting_key(key)
    assert not is_secret(key, "30")


def test_credentials_in_connection_strings_are_found_and_replaced_keeping_scheme_and_host():
    for value in (ORACLE, "jdbc:oracle:oci:scott/tiger@db", "jdbc:postgresql://u:pw@host/db", "amqp://u:pw@mq:5672"):
        assert has_embedded_credentials(value) and looks_like_secret_value(value)
        assert is_secret("Url", value)
    assert redact_embedded_credentials(ORACLE) == ("jdbc:oracle:thin:[redacted]@db:1521/X", 1)
    assert redact_secret_text(f"url={ORACLE}") == "url=jdbc:oracle:thin:[redacted]@db:1521/X"
    for value in ("jdbc:oracle:thin:@//db:1521/X", "https://example.com/a/b@c", "@scope/pkg@1.0"):
        assert not has_embedded_credentials(value)


def test_the_judge_probes_never_reach_a_configured_setting_value():
    text = "[Db]\n" + "".join(f"{key} = {value}\n" for key, value in PROBES.items()) + f"Url = {ORACLE}\n"
    entries = parse_ini(text, (";", "#"), ("+",)).entries
    assert len(entries) == len(PROBES) + 1
    assert all(entry.redacted and entry.value == "[redacted]" for entry in entries)
    assert "tiger" not in repr(entries) and "changeit" not in repr(entries) and "geheim" not in repr(entries)
    properties = parse_properties(f"keystore.pass=changeit\ndb.url={ORACLE}\n").entries
    assert all(entry.redacted for entry in properties)
    yaml_entries = parse_yaml("db:\n  Pwd: abc\n  url: " + ORACLE + "\n").entries
    assert all(entry.redacted for entry in yaml_entries)


def test_a_config_file_loses_its_secret_values_in_the_stored_text_with_every_line_in_place():
    text = (
        "[Db]\n"
        "KeystorePass = changeit\n"
        "Pwd=abc\n"
        "; Passwort = in a comment stays a comment\n"
        "Passwort = geheim\n"
        "+ continued-secret\n"
        f"Url = {ORACLE}\n"
        "Timeout = 30\n"
    )
    redacted = redact_repository_text(text, "conf/app.ini")
    lines = redacted.text.split("\n")
    assert len(lines) == len(text.split("\n"))
    assert lines[1] == "KeystorePass = [redacted]" and lines[2] == "Pwd=[redacted]"
    assert lines[4] == "Passwort = [redacted]" and lines[5] == "[redacted]"
    assert lines[6] == "Url = jdbc:oracle:thin:[redacted]@db:1521/X" and lines[7] == "Timeout = 30"
    for secret in ("changeit", "abc", "geheim", "continued-secret", "tiger"):
        assert secret not in redacted.text
    assert redacted.redactions == 5


def test_yaml_properties_and_env_files_are_config_files_too():
    yaml_text = "db:\n  password: |\n    line-one\n    line-two\n  user: app\n"
    assert redact_repository_text(yaml_text, "chart/values.yaml").text == (
        "db:\n  password: |\n    [redacted]\n    [redacted]\n  user: app\n"
    )
    properties = "spring.datasource.password=petclinic\nkeystore.pass=a\\\n  b\nname=x\n"
    assert redact_repository_text(properties, "src/main/resources/application.properties").text == (
        "spring.datasource.password=[redacted]\nkeystore.pass=[redacted]\n  [redacted]\nname=x\n"
    )
    assert redact_repository_text("export DB_PWD=abc\n", ".env.local").text == "export DB_PWD=[redacted]\n"
    assert is_config_path("conf/app.ini-prod") and not is_config_path("src/Main.java")


def test_source_code_keeps_its_assignments_but_never_a_connection_secret():
    code = f'String password = getPassword();\nString url = "{ORACLE}";\n'
    redacted = redact_repository_text(code, "src/Db.java")
    assert redacted.text.startswith("String password = getPassword();\n")
    assert "tiger" not in redacted.text
    # Without a path (or for code) a ``password=`` assignment stays: the name is the fact.
    assert redact_repository_text("spring.datasource.password=petclinic\n").text == (
        "spring.datasource.password=petclinic\n"
    )

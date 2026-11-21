"""Offline loader and internal-consistency checks for dependency adoption-gate manifests.

The manifest records one component adoption gate: the exact candidate distribution version, the resolved dependency
closure with artifact digests and provenance, the distributions and extras explicitly excluded from that closure, the
recorded advisory findings with their remediation decision, and the gate outcome with classified blockers. This module
never touches the network and never resolves dependencies; it only validates that the recorded evidence is internally
consistent and that every recorded decision is tied to recorded evidence.

Comparison against the repository state (``backend/pyproject.toml``, ``backend/uv.lock``) lives in
``dependency_gates.repository_drift``.

A consistency failure means the recorded evidence is stale or the decision text and the evidence have diverged, not
that the repository is wrong. The correct response is to re-run the gate, not to edit the manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "octryx.dependency-gate/v1"
DIGEST_FIELD = "manifest_sha256"
_HEX = set("0123456789abcdef")
_VALID_ORIGINS = frozenset({"already_locked", "introduced", "upgraded"})

# Whether the PyPI PEP 740 provenance endpoint was consulted for a distribution. ``not_queried`` is not evidence of
# absence: PEP 740 provenance is per artifact, so a distribution that publishes many platform wheels has no single
# platform-independent artifact this gate could query.
_VALID_ATTESTATION_QUERIES = frozenset({"queried", "not_queried", "query_failed"})
ATTESTED = "attested"
NO_ATTESTATION = "no_attestation"
ATTESTATION_UNKNOWN = "attestation_unknown"

# What a blocker is about. One blocker per kind keeps the decision record de-duplicated.
_BLOCKER_KINDS = frozenset(
    {
        "resolution_conflict",
        "duplicate_http_stack",
        "provider_credential_discovery",
        "fallback_and_gateway_surface",
        "provenance_gap",
        "advisory_open",
    }
)

# Where a blocker comes from. ``candidate_intrinsic`` means no release choice or repository change avoids it;
# ``repository_state`` means the current repository state causes it and it would exist without this candidate;
# ``activation_boundary`` means it is only preventable by an Octryx-owned adapter boundary that does not exist
# yet. A blocker without ``candidate_intrinsic`` must never be reported as a defect of the candidate.
_BLOCKER_CLASSIFICATIONS = frozenset({"candidate_intrinsic", "repository_state", "activation_boundary"})

# How an approved gate answered each gate-time blocker. An accepted exception must say when it was granted.
_APPROVAL_RESOLUTION_KINDS = frozenset({"lock_move_reviewed", "accepted_exception", "closed_by_boundary", "remediated"})
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

_ADVISORY_ID = re.compile(r"\b(?:GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}|CVE-\d{4}-\d{4,})\b")

# The field a remediation decision must carry to say that approval does not require the recorded floor. Not every
# advisory is an approval blocker, so a waiver stays possible — but it may never be silent, because a bare
# ``required_before_approval: false`` is indistinguishable from an overlooked finding.
WAIVER_FIELD = "approval_waiver_rationale"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = BACKEND_ROOT / "pyproject.toml"
UV_LOCK_PATH = BACKEND_ROOT / "uv.lock"


def canonical_name(name: str) -> str:
    """Return the PEP 503 canonical distribution name so lock, pyproject and PyPI spellings compare equal."""
    return re.sub(r"[-_.]+", "-", name).lower()


class GateDriftError(AssertionError):
    """Raised when recorded gate evidence no longer matches the repository or is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class GateManifest:
    """A loaded adoption-gate manifest."""

    path: Path
    payload: dict[str, Any]

    @property
    def distribution(self) -> str:
        return str(self.payload["distribution"])

    @property
    def candidate_version(self) -> str:
        return str(self.payload["candidate_version"])

    @property
    def approved_for_installation(self) -> bool:
        return bool(self.payload["approved_for_installation"])

    @property
    def closure(self) -> list[dict[str, Any]]:
        return list(self.payload["closure"])

    @property
    def excluded_distributions(self) -> list[str]:
        return list(self.payload["excluded_distributions"])

    @property
    def blockers(self) -> list[dict[str, Any]]:
        return list(self.payload.get("blockers") or [])

    @property
    def approval(self) -> dict[str, Any]:
        return dict(self.payload.get("approval") or {})

    @property
    def recorded_blockers(self) -> list[dict[str, Any]]:
        """The blockers the gate evidence is about: open ones while blocked, the resolved ones once approved."""
        if self.approved_for_installation:
            return list(self.approval.get("resolved_blockers") or [])
        return self.blockers

    @property
    def advisories(self) -> dict[str, Any]:
        return dict(self.payload["advisories"])

    @property
    def advisory_remediation(self) -> dict[str, dict[str, Any]]:
        """Per-distribution decision for every recorded advisory finding, with the floor approval requires."""
        return dict(self.payload.get("advisory_remediation") or {})

    @property
    def compatibility_floors(self) -> dict[str, str]:
        return dict(self.payload.get("compatibility_floors") or {})

    @property
    def universal_lock_only_distributions(self) -> list[str]:
        """Distributions a universal lock pins under a marker that never installs on a supported runtime platform."""
        return list(self.payload.get("universal_lock_only_distributions") or [])


def attestation_state(entry: dict[str, Any]) -> str:
    """Classify a closure entry's PEP 740 provenance, keeping "not queried" distinct from "queried, none published"."""
    if entry.get("pypi_attestation_publisher"):
        return ATTESTED
    if entry.get("attestation_query") == "queried":
        return NO_ATTESTATION
    return ATTESTATION_UNKNOWN


def satisfies_floor(version: str, floor: str) -> bool:
    """Compare dotted release segments without a packaging dependency; ``floor`` is a bare minimum version."""

    def parts(value: str) -> list[int]:
        out: list[int] = []
        for chunk in value.split("."):
            digits = "".join(c for c in chunk if c.isdigit())
            out.append(int(digits) if digits else 0)
        return out

    left, right = parts(version), parts(floor)
    width = max(len(left), len(right))
    left += [0] * (width - len(left))
    right += [0] * (width - len(right))
    return left >= right


def canonical_payload_digest(payload: dict[str, Any]) -> str:
    """Return the SHA-256 over the canonical JSON form of ``payload`` without its own digest field."""
    body = {key: value for key, value in payload.items() if key != DIGEST_FIELD}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_manifest(path: Path) -> GateManifest:
    """Load a manifest and verify its schema, digest and internal consistency."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema = payload.get("schema")
    if schema != MANIFEST_SCHEMA:
        raise GateDriftError(f"{path.name}: unsupported schema {schema!r}, expected {MANIFEST_SCHEMA!r}")

    recorded = payload.get(DIGEST_FIELD)
    computed = canonical_payload_digest(payload)
    if recorded != computed:
        raise GateDriftError(
            f"{path.name}: manifest digest drift; recorded {recorded!r} but content hashes to {computed!r}. "
            f"Re-run the gate regeneration instead of editing the manifest by hand."
        )

    manifest = GateManifest(path=path, payload=payload)
    _check_internal_consistency(manifest)
    return manifest


def _check_internal_consistency(manifest: GateManifest) -> None:
    closure = manifest.closure
    if not closure:
        raise GateDriftError(f"{manifest.path.name}: closure is empty")

    names = [entry["name"] for entry in closure]
    if names != sorted(names):
        raise GateDriftError(f"{manifest.path.name}: closure entries are not sorted by name")
    if len(set(names)) != len(names):
        raise GateDriftError(f"{manifest.path.name}: closure contains duplicate distribution names")
    if manifest.distribution not in names:
        raise GateDriftError(
            f"{manifest.path.name}: gated distribution {manifest.distribution!r} is not in the closure"
        )

    for entry in closure:
        _check_closure_entry(manifest, entry)

    overlap = sorted(set(manifest.excluded_distributions) & set(names))
    if overlap:
        raise GateDriftError(
            f"{manifest.path.name}: distributions are both excluded and present in the closure: {overlap}"
        )

    lock_only_overlap = sorted(set(manifest.universal_lock_only_distributions) & set(names))
    if lock_only_overlap:
        raise GateDriftError(
            f"{manifest.path.name}: distributions are recorded as universal-lock-only but are in the installed "
            f"closure: {lock_only_overlap}"
        )

    _check_blockers(manifest)
    _check_advisories(manifest)


def _check_closure_entry(manifest: GateManifest, entry: dict[str, Any]) -> None:
    name = entry["name"]
    if canonical_name(name) != name:
        raise GateDriftError(f"{manifest.path.name}: {name!r} is not a PEP 503 canonical distribution name")
    if entry["origin"] not in _VALID_ORIGINS:
        raise GateDriftError(f"{manifest.path.name}: {name} has unknown origin {entry['origin']!r}")
    digest = entry.get("sdist_sha256") or ""
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise GateDriftError(f"{manifest.path.name}: {name} has no usable sdist SHA-256")
    if not entry.get("license"):
        raise GateDriftError(f"{manifest.path.name}: {name} has no recorded license")
    if not (entry.get("source") or entry.get("pypi_attestation_publisher") or entry.get("reviewed_provenance")):
        raise GateDriftError(
            f"{manifest.path.name}: {name} has neither a PyPI source URL, a PEP 740 attestation, nor a "
            f"reviewed provenance note"
        )
    if entry["name"] == manifest.distribution and entry["version"] != manifest.candidate_version:
        raise GateDriftError(
            f"{manifest.path.name}: closure pins {name}=={entry['version']} but the candidate version is "
            f"{manifest.candidate_version}"
        )
    _check_attestation_record(manifest, entry)


def _check_attestation_record(manifest: GateManifest, entry: dict[str, Any]) -> None:
    """A provenance gap must say whether the endpoint was consulted; silence must never read as a negative result."""
    name = entry["name"]
    query = entry.get("attestation_query")
    if query not in _VALID_ATTESTATION_QUERIES:
        raise GateDriftError(
            f"{manifest.path.name}: {name} records attestation_query {query!r}, expected one of "
            f"{sorted(_VALID_ATTESTATION_QUERIES)}"
        )
    note = entry.get("attestation_query_note")
    if query == "queried":
        if note:
            raise GateDriftError(f"{manifest.path.name}: {name} was queried but also records a skip note")
        if (entry.get("wheel_count") or 0) != 1:
            raise GateDriftError(
                f"{manifest.path.name}: {name} records a per-artifact attestation query but publishes "
                f"{entry.get('wheel_count')} wheels, so no single platform-independent artifact was queryable"
            )
    else:
        if not note:
            raise GateDriftError(f"{manifest.path.name}: {name} records attestation_query {query!r} without a reason")
        if entry.get("pypi_attestation_publisher"):
            raise GateDriftError(
                f"{manifest.path.name}: {name} records an attestation publisher although the query was {query!r}"
            )


def _check_blockers(manifest: GateManifest) -> None:
    """An approved gate carries no blockers; a blocked gate must classify each one and tie it to recorded evidence."""
    name = manifest.path.name
    blockers = manifest.blockers
    if manifest.approved_for_installation:
        if blockers:
            raise GateDriftError(f"{name}: gate is marked approved for installation but still records blockers")
        _check_approval(manifest)
    elif not blockers:
        raise GateDriftError(f"{name}: gate is not approved but records no blockers")
    _check_blocker_records(name, manifest.recorded_blockers)
    _check_provenance_gap_blocker(manifest)


def _check_approval(manifest: GateManifest) -> None:
    """An approved gate names its date and answers every gate-time blocker; silence is not an approval."""
    name = manifest.path.name
    approval = manifest.approval
    if not _ISO_DATE.fullmatch(str(approval.get("approved_on") or "")):
        raise GateDriftError(f"{name}: gate is approved but records no approval date")
    resolved = approval.get("resolved_blockers") or []
    if not resolved:
        raise GateDriftError(f"{name}: gate is approved but its approval answers no gate-time blocker")
    for blocker in resolved:
        kind = blocker.get("resolution_kind")
        if kind not in _APPROVAL_RESOLUTION_KINDS:
            raise GateDriftError(
                f"{name}: {blocker.get('id')} has resolution kind {kind!r}, expected one of "
                f"{sorted(_APPROVAL_RESOLUTION_KINDS)}"
            )
        if not str(blocker.get("resolution") or "").strip():
            raise GateDriftError(f"{name}: {blocker.get('id')} records no resolution")
        if kind == "accepted_exception" and not _ISO_DATE.fullmatch(str(blocker.get("exception_granted_on") or "")):
            raise GateDriftError(f"{name}: {blocker.get('id')} is an accepted exception without a grant date")


def _check_blocker_records(name: str, blockers: list[dict[str, Any]]) -> None:
    ids = [str(blocker.get("id") or "") for blocker in blockers]
    if ids != sorted(ids) or len(set(ids)) != len(ids) or not all(ids):
        raise GateDriftError(f"{name}: blocker ids must be present, unique and sorted, got {ids}")
    kinds = [blocker.get("kind") for blocker in blockers]
    if len(set(kinds)) != len(kinds):
        raise GateDriftError(f"{name}: blocker kinds must be unique, got {kinds}")

    for blocker in blockers:
        if blocker.get("kind") not in _BLOCKER_KINDS:
            raise GateDriftError(
                f"{name}: {blocker['id']} has unknown kind {blocker.get('kind')!r}, expected one of "
                f"{sorted(_BLOCKER_KINDS)}"
            )
        classifications = blocker.get("classifications") or []
        unknown = sorted(set(classifications) - _BLOCKER_CLASSIFICATIONS)
        if not classifications or unknown:
            raise GateDriftError(
                f"{name}: {blocker['id']} must carry at least one known classification from "
                f"{sorted(_BLOCKER_CLASSIFICATIONS)}; unknown entries: {unknown}"
            )
        if not str(blocker.get("statement") or "").strip():
            raise GateDriftError(f"{name}: {blocker['id']} records no statement")


def _check_provenance_gap_blocker(manifest: GateManifest) -> None:
    """The provenance blocker must cite exactly the distributions this gate would introduce without an attestation."""
    blocker = next((b for b in manifest.recorded_blockers if b.get("kind") == "provenance_gap"), None)
    if blocker is None:
        return
    cited = list(blocker.get("cited_distributions") or [])
    derived = sorted(
        {
            entry["name"]
            for entry in manifest.closure
            if entry["origin"] == "introduced" and attestation_state(entry) != ATTESTED
        }
        | set(manifest.universal_lock_only_distributions)
    )
    if cited != derived:
        raise GateDriftError(
            f"{manifest.path.name}: {blocker['id']} cites {cited} but the recorded closure evidence derives "
            f"{derived}; pre-existing dependencies are out of this gate's scope and attested ones are not a gap"
        )
    missing_from_prose = [distribution for distribution in cited if distribution not in blocker["statement"]]
    if missing_from_prose:
        raise GateDriftError(
            f"{manifest.path.name}: {blocker['id']} does not name {missing_from_prose} in its statement"
        )


def _check_advisories(manifest: GateManifest) -> None:
    """Every recorded finding needs a remediation decision, and every cited identifier needs a recorded finding."""
    name = manifest.path.name
    advisories = manifest.advisories
    if not advisories.get("source") or not advisories.get("queried_at_utc"):
        raise GateDriftError(f"{name}: advisories record no query source or timestamp")

    findings = {(finding["distribution"], finding["id"]) for finding in advisories["findings"]}
    aliases = dict(advisories.get("recorded_aliases") or {})
    unknown_alias = sorted(set(aliases) - {advisory_id for _, advisory_id in findings})
    if unknown_alias:
        raise GateDriftError(f"{name}: recorded aliases reference advisories that are not recorded findings: "
                             f"{unknown_alias}")
    if aliases and not advisories.get("alias_provenance"):
        raise GateDriftError(f"{name}: recorded advisory aliases carry no provenance note")

    remediation = manifest.advisory_remediation
    closure_names = {entry["name"] for entry in manifest.closure}
    decided: set[tuple[str, str]] = set()
    for distribution, decision in sorted(remediation.items()):
        if distribution not in closure_names:
            raise GateDriftError(f"{name}: advisory remediation targets {distribution}, which is not in the closure")
        if not decision.get("enforced_floor"):
            raise GateDriftError(f"{name}: advisory remediation for {distribution} records no enforced floor")
        for advisory_id in decision.get("advisories") or []:
            decided.add((distribution, advisory_id))

    undecided = sorted(findings - decided)
    if undecided:
        raise GateDriftError(f"{name}: advisory findings without a recorded remediation decision: {undecided}")
    unbacked = sorted(decided - findings)
    if unbacked:
        raise GateDriftError(f"{name}: advisory remediation references findings that are not recorded: {unbacked}")

    _check_advisory_approval_decisions(manifest, findings, remediation)

    known = {advisory_id for _, advisory_id in findings} | set(aliases.values())
    for blocker in manifest.recorded_blockers:
        cited = set(_ADVISORY_ID.findall(blocker["statement"]))
        unmatched = sorted(cited - known)
        if unmatched:
            raise GateDriftError(
                f"{name}: {blocker['id']} cites {unmatched}, which match no recorded advisory finding or alias"
            )
        if blocker["kind"] != "advisory_open":
            continue
        if not cited:
            raise GateDriftError(f"{name}: {blocker['id']} is an advisory blocker but cites no recorded advisory")
        for distribution in blocker.get("cited_distributions") or []:
            decision = remediation.get(distribution)
            if not decision or not decision.get("required_before_approval"):
                raise GateDriftError(
                    f"{name}: {blocker['id']} cites {distribution} but records no remediation floor that approval "
                    f"requires"
                )


def _check_advisory_approval_decisions(
    manifest: GateManifest,
    findings: set[tuple[str, str]],
    remediation: dict[str, dict[str, Any]],
) -> None:
    """A recorded advisory finding is either an approval precondition or an explicitly reasoned waiver.

    This is the governance invariant behind ``required_before_approval``. Dropping a distribution from the advisory
    blocker's ``cited_distributions`` is enough to escape the blocker-side check above, so without this rule a recorded
    finding could be downgraded to ``required_before_approval: false`` and disappear from the decision record with no
    trace. The rule does not assume every advisory is an approval blocker: it only refuses the silent case, where the
    manifest carries a finding and says nothing about why approval no longer needs its floor.
    """
    for distribution in sorted({distribution for distribution, _ in findings}):
        decision = remediation.get(distribution) or {}
        if decision.get("required_before_approval"):
            continue
        if not str(decision.get(WAIVER_FIELD) or "").strip():
            advisories = ", ".join(sorted(advisory for dist, advisory in findings if dist == distribution))
            raise GateDriftError(
                f"{manifest.path.name}: advisory remediation for {distribution} ({advisories}) neither requires its "
                f"floor before approval nor records a {WAIVER_FIELD}; a recorded advisory may not be waived silently"
            )

"""Configuration files plus Git: the configuration layer of one repository file revision.

Selected: the current revision of every indexed file (``knowledge_code_files``) of a profile
connector kind (``git_repository``) whose file name matches a profile file rule (``*.ini``,
``*.properties``, ``values*.yaml``). The text read is the stored object, which the code ingest
already redacted line-preserving; :mod:`.config_files` masks secret-looking values once more.

Per file: a ``ConfigFile`` node, the ``AppComponent`` it ``configures`` (its top-level directory,
``conf`` or ``worker``; the repository for a top-level file), one ``ConfiguredSetting`` per key with
its section, the section's plugin type and the 1-based line, and the file's ``base_path`` (the
path itself, or the base file of a profile variant: ``app.ini-test`` → ``app.ini``, with
``variant`` ``test``), ``defines`` edges, ``mentions`` of
ticket keys in the comments above a key (or anywhere in the file), and ``changes_file`` from the
commit that introduced the file's current blob (``knowledge_code_file_blobs.first_commit``; the
snapshot keeps no commit messages). Every citation is the code span that covers the line.
"""

from __future__ import annotations

import fnmatch
import posixpath

from sqlalchemy import select

from ....models.project.knowledge_code_files import KnowledgeCodeFile, KnowledgeCodeFileBlob
from ....models.project.knowledge_evidence import REVISION_STATE_PROJECTED, KnowledgeSourceHead, KnowledgeSourceRevision
from ....models.project.knowledge_source_sync import KnowledgeSourceConnector
from .config_files import parse_config
from .facts import Extraction, NodeRef
from .profile_patterns import ProfilePattern
from .profile_types import ConfigFileRule
from .sources import Candidate, current_revisions, load_span_inputs
from .texts import SpanIndex, read_revision_text
from .tickets import find_tickets, jira_pattern, jira_project_keys, ticket_key

EXTRACTOR = "config-rules"
MEMO_FILES = "config_files"


def rule_for(path: str, rules: tuple[ConfigFileRule, ...]) -> ConfigFileRule | None:
    name = posixpath.basename(path)
    return next((rule for rule in rules if fnmatch.fnmatchcase(name, rule.glob)), None)


def variant_of(path: str, patterns: tuple[ProfilePattern, ...]) -> tuple[str, str | None]:
    """``(base path, variant)`` of a file: ``conf/app.ini-test`` → ``("conf/app.ini", "test")``."""
    folder, name = posixpath.split(path)
    for pattern in patterns:
        found = pattern.fullmatch(name)
        if found and found.group("base") and found.group("variant"):
            return posixpath.join(folder, found.group("base")), found.group("variant")
    return path, None


async def select_config_files(context) -> list[Candidate]:
    profile = context.profile
    rows = await context.db.execute(
        select(
            KnowledgeCodeFile.revision_id, KnowledgeCodeFile.path, KnowledgeCodeFile.commit_sha,
            KnowledgeCodeFile.blob_sha, KnowledgeCodeFile.path_digest, KnowledgeCodeFile.connector_id,
            KnowledgeSourceConnector.connector_key, KnowledgeSourceConnector.scope,
        )
        .join(KnowledgeSourceConnector, KnowledgeSourceConnector.id == KnowledgeCodeFile.connector_id)
        .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == KnowledgeCodeFile.revision_id)
        .join(KnowledgeSourceHead, KnowledgeSourceHead.current_revision_id == KnowledgeSourceRevision.id)
        .where(
            KnowledgeCodeFile.project_id == context.project_id,
            KnowledgeSourceConnector.kind.in_(profile.config_connector_kinds),
            KnowledgeSourceRevision.state == REVISION_STATE_PROJECTED,
        )
    )
    files: dict[str, dict] = {}
    for revision_id, path, commit, blob, digest, connector_id, connector_key, scope in rows.all():
        rule = rule_for(path, profile.config_files)
        if rule is None:
            continue
        repo = str((scope or {}).get("display_name") or connector_key)
        files[str(revision_id)] = {"rule": rule, "path": path, "repo": repo, "commit": commit, "blob": blob,
                                   "digest": digest, "connector_id": connector_id}
    context.memo[MEMO_FILES] = files
    return await current_revisions(context.db, context.project_id, revision_ids=tuple(sorted(files)))


async def _first_commit(context, info: dict) -> str | None:
    row = await context.db.execute(
        select(KnowledgeCodeFileBlob.first_commit).where(
            KnowledgeCodeFileBlob.connector_id == info["connector_id"],
            KnowledgeCodeFileBlob.path_digest == info["digest"],
            KnowledgeCodeFileBlob.blob_sha == info["blob"],
        )
    )
    return row.scalar_one_or_none() or info["commit"]


async def extract_config_file(context, candidate: Candidate) -> tuple[str, Extraction]:
    info = context.memo[MEMO_FILES][candidate.revision_id]
    rule: ConfigFileRule = info["rule"]
    profile = context.profile
    if "jira" not in context.memo:
        context.memo["jira"] = jira_pattern(await jira_project_keys(context.db, context.project_id))
    index = SpanIndex.of(await load_span_inputs(context.db, context.project_id, candidate.revision_id))
    cite = index.at_line
    parsed = parse_config(
        await read_revision_text(context, candidate), rule.format,
        profile.comment_prefixes[rule.format], profile.continuation_prefixes,
    )
    extraction = Extraction()
    repo, path = info["repo"], info["path"]
    component = path.split("/", 1)[0] if "/" in path else repo
    base_path, variant = variant_of(path, profile.variant_patterns)
    file_ref = extraction.node("ConfigFile", f"{repo}:{path}", path, cite(1), repo=repo, path=path,
                               format=rule.format, component=component, manual_documented=rule.manual_documented,
                               base_path=base_path, variant=variant)
    app = extraction.node("AppComponent", f"app-component:{repo}/{component}", component, cite(1),
                          repo=repo, component=component)
    extraction.edge("configures", file_ref, app, cite(1))
    commit = await _first_commit(context, info)
    if commit:
        commit_ref = extraction.node("Commit", f"commit:{repo}@{commit}", commit[:12], cite(1), repo=repo, sha=commit)
        extraction.edge("changes_file", commit_ref, file_ref, cite(1), basis="first_commit_of_blob")
    types = parsed.section_types(context.profile.registry_sections)
    attached: set[int] = set()
    for entry in parsed.entries:
        key = f"{repo}:{path}|{entry.section}|{entry.key}"
        if NodeRef("ConfiguredSetting", key) in extraction.nodes:
            extraction.warn("setting_repeated")
            key = f"{key}@{entry.line}"
        label = f"[{entry.section}] {entry.key}" if entry.section else entry.key
        setting = extraction.node(
            "ConfiguredSetting", key, label, cite(entry.line), repo=repo, path=path, format=rule.format,
            component=component, section=entry.section or None,
            section_type=types.get(entry.section, entry.section) or None, key=entry.key, value=entry.value,
            redacted=entry.redacted, line=entry.line,
            manual_documented=rule.manual_documented, base_path=base_path, variant=variant,
        )
        extraction.edge("defines", file_ref, setting, cite(entry.line))
        for line, text in entry.comments:
            attached.add(line)
            for node_type, number in find_tickets(text, context.profile, context.memo["jira"]):
                ticket = extraction.node(node_type, ticket_key(node_type, number), number, cite(line), number=number,
                                         stub=True)
                extraction.edge("mentions", setting, ticket, cite(line))
    for line, text in parsed.comments:
        if line in attached:
            continue
        for node_type, number in find_tickets(text, context.profile, context.memo["jira"]):
            ticket = extraction.node(node_type, ticket_key(node_type, number), number, cite(line), number=number,
                                     stub=True)
            extraction.edge("mentions", file_ref, ticket, cite(line))
    if parsed.truncated:
        extraction.warn("settings_truncated")
    if parsed.skipped_lines:
        extraction.warn("lines_not_parsed", parsed.skipped_lines)
    return EXTRACTOR, extraction


__all__ = ["EXTRACTOR", "extract_config_file", "rule_for", "select_config_files", "variant_of"]

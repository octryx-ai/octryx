"""Shared helpers for the test_knowledge_parsed_documents_* modules."""

from __future__ import annotations

import dataclasses

import httpx

from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.ingestion.docling_client import DoclingSandboxConfig, DoclingSandboxParser
from app.services.knowledge.ingestion.parser_port import ParserIdentity, TaskStatus
from app.services.knowledge.ingestion.sandboxed_ingest import ingest_sandboxed_source
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

PDF = b"%PDF-1.7\nspec\n"


IDENTITY = ParserIdentity(name="docling-serve", version="1.35.0+p1", sandbox="no_network_uds")


def _text(index: int, label: str, text: str, page: int, **extra) -> dict:
    return {"self_ref": f"#/texts/{index}", "label": label, "text": text, "prov": [{"page_no": page}], **extra}


def _document() -> dict:
    texts = [
        _text(0, "page_header", "Example Corp confidential", 1),
        _text(1, "title", "Order Shipping Protocol", 1),
        _text(2, "document_index", "1 Introduction ........ 3", 1),
        _text(3, "section_header", "Message Flow", 2, level=1),
        _text(4, "text", "The carrier answers the order request with a receipt.", 2),
        _text(5, "section_header", "Challenge", 3, level=2),
        _text(6, "list_item", "The CReq carries the challenge data.", 3, marker="1."),
        _text(7, "caption", "Figure 3: challenge flow", 3),
        _text(8, "text", "diagram label inside the picture", 3),
        _text(9, "caption", "Table 4: message versions", 4),
        _text(10, "page_footer", "Page 4", 4),
        _text(11, "section_header", "Error Handling", 5, level=1),
        _text(12, "text", "An Erro message ends the transaction.", 5),
    ]
    cell = lambda row, col, text: {"text": text, "start_row_offset_idx": row, "start_col_offset_idx": col}  # noqa: E731
    return {
        "body": {
            "children": [{"$ref": f"#/texts/{i}"} for i in (0, 1, 2, 3, 4, 5, 6)]
            + [{"$ref": "#/pictures/0"}, {"$ref": "#/tables/0"}, {"$ref": "#/texts/10"}]
            + [{"$ref": "#/texts/11"}, {"$ref": "#/texts/12"}]
        },
        "texts": texts,
        "pictures": [{"label": "picture", "captions": [{"$ref": "#/texts/7"}], "children": [{"$ref": "#/texts/8"}]}],
        "tables": [
            {
                "label": "table",
                "prov": [{"page_no": 4}],
                "captions": [{"$ref": "#/texts/9"}],
                "data": {
                    "grid": [
                        [cell(0, 0, "Version"), cell(0, 1, "Status")],
                        [cell(1, 0, "2.3.1"), cell(1, 1, "current")],
                    ]
                },
            }
        ],
        "groups": [],
    }


@dataclasses.dataclass
class FakeSandbox:
    polls: list[TaskStatus]
    identity: ParserIdentity = IDENTITY
    submitted: list[bytes] = dataclasses.field(default_factory=list)
    options: list[dict] = dataclasses.field(default_factory=list)

    async def submit(self, data: bytes, media_type: str, *, do_ocr: bool = True, page_range=None) -> str:
        assert media_type == "application/pdf"
        self.submitted.append(data)
        self.options.append({"do_ocr": do_ocr, "page_range": page_range})
        return f"task-{len(self.submitted)}"

    async def poll(self, task_ref: str) -> TaskStatus:
        return self.polls.pop(0)

    async def result(self, task_ref: str) -> dict:
        return _document()


async def _setup(db, sandbox: FakeSandbox):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, s3, evidence_index = build_runtime()
    return authorized, user_id, dataclasses.replace(runtime, parser=sandbox), s3


async def _upload(db, runtime, authorized, user_id):
    return await ingest_sandboxed_source(
        db,
        runtime=runtime,
        authorized=authorized,
        source_key="shipping-core",
        display_title="Shipping Core Spec",
        declared_media_type="application/pdf",
        data=PDF,
        created_by=user_id,
        source_url="https://docs.example.com/shipping/core.pdf",
    )


def _sandbox(handler) -> DoclingSandboxParser:
    config = DoclingSandboxConfig(socket_path="/run/octryx-parser/docling.sock", version="1.35.0")
    return DoclingSandboxParser(config, transport=httpx.MockTransport(handler))

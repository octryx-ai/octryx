# Ingestion: spans and evidence keys

Same bytes, same derivation path and same configuration in, same spans out, so a projection can be rebuilt from the
stored object without breaking a citation already handed out. A text-native span depends only on the decoded text;
a parsed document's offsets point into text built from the parser's output, so the recorded parser identity
(name and version), the outline and the admonition markers are part of that configuration.

## Span derivation of text-native input (`spans.py`)

1. Decode as strict UTF-8. Bytes that do not decode are refused as an unsupported media type; nothing is decoded
   leniently.
2. Normalize line endings to `\n` and drop unsafe characters, with the rule the retrieval contract enforces, so a
   stored span can always be built into `Evidence`.
3. Split on blank lines into paragraphs. A paragraph longer than `MAX_SPAN_CHARS` is wrapped at the last space inside
   the bound, or cut at the bound when it has none.
4. Number the spans from 1 and record each one's `[char_start, char_end)` in the normalized text, the text the
   digest-verified bytes decode to.

Markdown and AsciiDoc (`text_outline.py`), code (`code/chunking.py`) and parsed documents (`docling_document.py`)
group text differently but keep ordinals from 1 and offsets into the text they cut, which for a parsed document is
the parser-built text, not the decoded bytes.

Two bounds, independent of each other: a revision's bytes (`MAX_UPLOAD_BYTES`) and its span count
(`MAX_SPANS_PER_REVISION`). A document inside the byte bound with more spans is a capacity refusal
(`EvidenceSpanLimitExceededError`, HTTP 413), not a malformed request.

## Evidence key

`<revision id as 32 hex>:<span ordinal>`, for example `3f2a...9c:7`. It is checked against the retrieval contract's
evidence-id rule (`retrieval/contracts.is_valid_evidence_id`), so a derived key is never refused later. A revision id
is never all digits (`new_revision_id`), so a key never looks like a database record id (`12:0`), which that rule
rejects.

## Citation

`<title> (rev <revision ordinal>, chars <start>-<end>[, § <section>])`; a code span says `lines <start>-<end>`, a
located span from a parsed document `p. <page>` or `pp. <first>-<last>`. A display title is at most
`MAX_DISPLAY_TITLE_CHARS` (300) characters; a longer one is refused, never cut. In the citation the section label is
capped at 120 characters, and the title is trimmed to what `MAX_CITATION_CHARS` (512) leaves after the suffix, so a
citation always names its revision and its range.

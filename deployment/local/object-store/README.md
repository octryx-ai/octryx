# Local S3-compatible object store (Knowledge object boundary)

Private, local-only S3-compatible runtime and live protocol acceptance for the Knowledge
object boundary
(`backend/app/services/knowledge/objects`), extended with the operator-owned reconciliation capability.
Not a production, EKS, or shared-environment manifest.

| File | Purpose |
|---|---|
| `compose.yaml` | Dedicated Compose project `octryx-object-store` (independent of the root `docker-compose.yml`) |
| `fixture.sh` | Deterministic start / readiness / smoke / cleanup, plus the generated test-only credentials |
| `product_smoke.py` | Live acceptance of the real `KnowledgeObjectStore` |
| `retention_smoke.py` | Live acceptance of the real `KnowledgeObjectMaintenance` (inventory + delete) |
| `fixture_contract.py` | The identity/bucket/Workspace contract shared with `fixture.sh`, and the credential intake |
| `fixture_client.py` | Fixture-only S3 client (bucket creation, planting a corrupt object, probing a refused read) |
| `wire_observer.py` | Passive botocore recorder proving which S3 operations the product issued |
| `.gitattributes` | Forces LF for `*.sh` here, even with `core.autocrlf=true` (a CRLF shebang breaks `./fixture.sh`) |

## Runbook

Run from this directory. The default interpreter is `../../../backend/.venv/bin/python`; in a
linked worktree without its own virtualenv, point `OBJECT_STORE_PYTHON` at the main checkout's
`backend/.venv/bin/python` (the smoke still imports the product code of the checkout it lives in).

```bash
./fixture.sh                    # provision -> up -> readiness -> product smoke -> cleanup
./fixture.sh up                 # start only
./fixture.sh smoke              # product smoke against an already started runtime
./fixture.sh down               # stop, remove, and verify nothing is left behind
```

Optional inputs: `OBJECT_STORE_S3_PORT` (default 8333), `OBJECT_STORE_STATE_DIR`
(default `$HOME/.config/octryx/object-store`), `OBJECT_STORE_PYTHON`.

On Rancher Desktop / Lima and Podman machine the state directory must be under a host path the
VM shares, typically `$HOME`; `/tmp` is not shared and Compose then fails with
"bind source path does not exist".

`./fixture.sh` is fail-closed throughout. A missing container runtime, an unrenderable Compose
file, an unavailable image, a runtime that does not become live, a running container that does not
match the pinned digest, an interpreter without boto3, any failing product check, or a cleanup that
leaves a container, volume or network behind all exit non-zero. Nothing is skipped and nothing
degrades to a pass.

## Selected component and license evidence

`ghcr.io/chrislusf/seaweedfs:4.47@sha256:ce9e796f1fe6f06968f4c04bdaf8f678dad9c8acdfef3d244133d71bfa6bf882`

- **Upstream**: `seaweedfs/seaweedfs`, tag `4.47` (released 2026-09-14). The running binary reports
  `version 30GB 4.47 c50733600`.
- **License**: Apache-2.0. Verified by reading `LICENSE` at tag `4.47`
  (`https://raw.githubusercontent.com/seaweedfs/seaweedfs/4.47/LICENSE`, 200 lines,
  SHA-256 `d789d433cc11da163273d1e39be2e8fa67642f9a58ef220d3f258fa9c14ef613`), and by the GitHub
  license API for the repository (`spdx_id: Apache-2.0`).
- **Image provenance**: built by the upstream repository's own workflow
  `.github/workflows/container_release_unified.yml` from `docker/Dockerfile.go_build`, published to
  `ghcr.io/chrislusf/seaweedfs` and copied to `docker.io/chrislusf/seaweedfs`. Both registries serve
  the **same** index digest `sha256:ce9e796f…6bf882`.
- **Platforms** in that index: `linux/amd64` (`sha256:f83509b0…320362`), `linux/arm64`
  (`sha256:d4cf6772…6cb32e`), plus `linux/386` and `linux/arm/v7`. amd64 covers the EKS node
  architecture, arm64 covers Apple Silicon development.
- **Not verified**: the image's cosign signature, an SBOM, and a CVE scan of the exact digest. Those
  belong to the component adoption gate, not to this local fixture.

The fixture requires `ChecksumSHA256` together with `IfNoneMatch: "*"`. The pinned SeaweedFS image
supports both on `PutObject`: the conditional write is refused with `ErrPreconditionFailed`, and a
checksum that disagrees with the body is refused with `ErrBadDigest`.

## Verified protocol behavior

`product_smoke.py` checks these responses through the real `KnowledgeObjectStore` against the
pinned digest:

| Product behavior | Server answer | Product state |
|---|---|---|
| `PutObject` with `ChecksumSHA256` **and** `IfNoneMatch: "*"`, path-style | `200`, echoes `ChecksumSHA256` | `created=True` |
| the same content address again | `412 PreconditionFailed` | `created=False`, no `HeadObject` |
| verified read | `200` with the stored bytes | bytes returned |
| stored bytes that do not hash to their address | `200` | `integrity_violation` |
| absent object | `404 NoSuchKey` | `not_found` (SeaweedFS; on AWS S3 without `s3:ListBucket` this is `403` -> `unauthorized`, see below) |
| absent bucket (grant present for the name) | `404 NoSuchBucket` | `needs_configuration` |
| no grant on the bucket | `403 AccessDenied` | `unauthorized` |
| wrong secret key | `403 SignatureDoesNotMatch` | `unauthorized` |
| unknown access key | `403 InvalidAccessKeyId` | `unauthorized` |
| a body whose `ChecksumSHA256` disagrees | `400 BadDigest` | not a product state: the product never sends a wrong checksum, so the smoke proves this **server capability** with the fixture identity instead |

`wire_observer.py` additionally proves, per phase, that the only operations the immutable store put
on the wire were `PutObject` and `GetObject`, that each request was path-style on the configured
loopback endpoint and signed, that every write carried `x-amz-checksum-sha256` and
`If-None-Match: *`, and that the Workspace and bucket refusals are decided locally with **no**
request at all.

### Reconciliation capability

`retention_smoke.py` drives the real `KnowledgeObjectMaintenance` with a separate identity that
holds **no** `Read` grant:

| Product behavior | Server answer | Product result |
|---|---|---|
| `ListObjectsV2` with `Prefix` = one Workspace's derived key prefix, bounded `MaxKeys` | `200` | one page of content addresses, sizes and write times (naive UTC) |
| a key under the Workspace prefix that the product never derives | `200`, key listed | counted as unrecognized, never a candidate, and `delete_one` refuses it |
| a bounded page followed by `StartAfter` = the last key | `200`, `IsTruncated` | every object returned exactly once, no server cursor retained |
| listing another Workspace | `200` | only that Workspace's objects; no key of the first appears |
| `delete_one` of another Workspace's key, or of a non-derived key | — | `not_found` with **no** request on the wire |
| `DeleteObject` of one own derived key | `204` | the object is gone, the sibling object is untouched |
| `GetObject` with the reconciliation identity (fixture-level) | `403 AccessDenied` | the identity cannot read Workspace bytes at all |

The observer asserts that the only operations this capability put on the wire were `ListObjectsV2`
and `DeleteObject`, and that **every** listing carried the Workspace prefix — a bucket-wide list
would fail the run. The smoke also asserts the two classes stay separate: the store never grows a
list/delete method and the maintenance capability never grows a read method.

## Least-privilege S3 operations

Two identities, two disjoint privilege sets. The application (API, runtime, ingestion, retrieval)
needs exactly two object actions and no bucket-level or listing action:

| Required on AWS S3 (IAM) — application identity | Why |
|---|---|
| `s3:PutObject` on `arn:aws:s3:::<bucket>/<prefix>/knowledge/*` | the only write; `IfNoneMatch` and `ChecksumSHA256` need no extra action |
| `s3:GetObject` on `arn:aws:s3:::<bucket>/<prefix>/knowledge/*` | the only read |

Nothing else: no `s3:DeleteObject`, `s3:ListBucket`, `s3:HeadObject` (covered by `s3:GetObject`),
`s3:AbortMultipartUpload`, `s3:PutObjectAcl`, `s3:GetBucketLocation` or `s3:CreateBucket`. Bucket
creation is a deployment step, not a runtime privilege.

The **operator reconciliation identity** is separate and is used only by the reconciliation
inventory (`backend/app/services/knowledge/retention/reconcile.py`), never by the API process:

| Required on AWS S3 (IAM) — reconciliation identity | Why |
|---|---|
| `s3:ListBucket` on `arn:aws:s3:::<bucket>`, conditioned on `s3:prefix` = `<prefix>/knowledge/*` | the bounded per-Workspace inventory |

Deliberately **not** `s3:GetObject`, `s3:PutObject` or `s3:DeleteObject`: the capability has no
read, write or delete operation, so the identity that reconciles a Workspace cannot read or alter
its content.

**`s3:ListBucket` is deliberately absent, and on AWS S3 that changes the absent-object state.**
AWS S3 answers `GetObject`/`HeadObject` for a key that does not exist with `404 NoSuchKey` only when
the caller also holds `s3:ListBucket` on the bucket; without it the answer is `403 AccessDenied`. The
product maps `403` to `unauthorized`, so under the least-privilege policy above an absent object on
AWS would be reported as `unauthorized` instead of `not_found`. This fixture cannot show that
divergence: measured against the pinned digest with the fixture's product identity, which holds no
list grant at all (`ListObjectsV2` -> `403 AccessDenied`), SeaweedFS still answers an absent key with
`404 NoSuchKey` (`HeadObject`: `404`). Deciding between adding `s3:ListBucket` (so `not_found` stays
distinguishable, at the cost of exposing key enumeration) and accepting `unauthorized` for a missing
object is an open AWS-activation decision, not something this local gate settles.

In this fixture the product identity is `octryx-local-smoke-knowledge-client` with
`Read:<bucket>`, `Write:<bucket>` and the same pair for the deliberately absent bucket. The
reconciliation identity is `octryx-local-smoke-retention-client` with `List:<bucket>` and `Write:<bucket>`
and **no** `Read` grant, which is why the fixture can show that it cannot read an object. Creating the
bucket and planting the corrupt object are done by a **separate** `octryx-local-smoke-fixture-admin`
identity on a separate boto3 session, so no product call ever runs with administrative rights.

## Interoperability limitations (honest scope)

One passing local implementation is not a statement about every S3-compatible vendor.

- **SeaweedFS grants are coarser than IAM.** `Write:<bucket>` also authorizes `DeleteObject`
  (verified: a delete of a stored object answers `204`), and `ReadBuckets`/`ListBuckets` is allowed
  for any authenticated identity. SeaweedFS therefore cannot express either least-privilege set
  above; AWS S3 can. The fixture proves the product *does not use* more than the actions listed per
  capability, not that the local server could stop it. Concretely: the reconciliation
  identity is granted `List` + `Write` because SeaweedFS has no delete-only action, so on this server
  it *could* also overwrite an object — on AWS the same role gets `s3:ListBucket` +
  `s3:DeleteObject` and cannot. What the fixture does show is that the identity holds no `Read`
  grant and that a `GetObject` with it is refused.
- **An absent object is only `not_found` because this server does not require a list grant.** See
  the `s3:ListBucket` note above: SeaweedFS answers `404 NoSuchKey` without any list grant, AWS S3
  would answer `403 AccessDenied` under the recorded least-privilege policy, and the product would
  then report `unauthorized`. The `not_found` result below is therefore a SeaweedFS observation, not
  an AWS one.
- **An absent bucket is only distinguishable when the identity is granted on its name.** With a
  bucket-scoped identity and no grant, SeaweedFS answers `AccessDenied` rather than `NoSuchBucket`,
  so the product would report `unauthorized` instead of `needs_configuration`. The smoke grants the
  absent bucket explicitly in order to exercise the `needs_configuration` mapping at all.
- **Error codes are per-implementation.** The product maps `PreconditionFailed`/`412`,
  `NoSuchKey`/`404`, `NoSuchBucket`, `AccessDenied`, `InvalidAccessKeyId` and
  `SignatureDoesNotMatch`. Those are the codes this digest returns; another vendor may return a
  different code for the same condition, which would surface as `contract_violation`.
- **No concurrency proof.** The duplicate path is exercised sequentially. That two simultaneous
  writers both get a correct answer relies on SeaweedFS evaluating the precondition under a
  per-object write lock, which is read from the upstream source, not measured here.
- **No versioning, object lock, replication, erasure coding, or multipart path** is exercised; the
  boundary uses none of them. A versioned bucket would need a versioned delete, which this capability
  deliberately does not implement.
- **Deletion is not raced against a concurrent write here.** The PostgreSQL hold, the settle window
  and the ledger re-verification that make a deletion safe against an in-flight ingestion are proven
  in `backend/tests/test_knowledge_object_retention_race.py`, not by this fixture: they are database
  behavior, not S3 protocol behavior.
- **Not qualified**: AWS S3 itself, and any customer-selected implementation. Both remain separate
  decisions.

## Security boundaries

- The S3 API is published on `127.0.0.1:${OBJECT_STORE_S3_PORT:-8333}` only. Master, volume and
  filer listen inside the container and are not published; the upstream Iceberg (`8181`) and Lance
  (`9101`) listeners are switched off.
- The container runs as the image's unprivileged `seaweed` user (`1000:1000`) with `cap_drop: ALL`,
  `no-new-privileges`, memory/CPU/PID limits and `restart: "no"`.
- All fixture data lives in a `tmpfs` at `/data`, so no named or anonymous volume is ever created
  and cleanup cannot leave data behind.
- **No egress.** SeaweedFS reports anonymous cluster statistics to `telemetry.seaweedfs.com` by
  default; `-master.telemetry=false` switches it off. A run's server log shows no telemetry activity.
- `-s3.autoCreateBucket=false`: the upstream default would let an admin identity create a bucket by
  writing to it, which would hide the `NoSuchBucket` state the product maps to
  `needs_configuration`.
- **Credentials.** Every run generates fresh random secret keys into a `0600` file outside the
  repository (`fixture.sh` refuses a state directory inside the checkout) and deletes them on
  cleanup. There is nothing to rotate, because no fixture data survives the container. The keys are
  never printed, never passed on a command line and never placed in a container's environment; the
  file is mounted as a read-only Compose secret. The access key ids are unmistakably local
  (`octryx-local-smoke-*`) and are not any product or vendor default.
- The product's own credential chain is narrowed before the first client exists: shared credentials
  and config files are pointed at `/dev/null`, IMDS is disabled, and `AWS_PROFILE`, role and
  container-credential variables are removed, so the smoke cannot reach a real AWS account.
- Nothing is printed except fixed labels and product state names: no credential, no object body, no
  `Authorization` header and no server error body. The fixture output, smoke output, logs and process
  arguments must omit credentials. Keep shell tracing off for `fixture.sh` (never run it with `bash -x`).

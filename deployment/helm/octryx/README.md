# Octryx AI Helm chart

Start from `../values.example.yaml`: it lists only what an installation has to decide. Every other value has a
working default in `values.yaml`.

## Image

No image is published. Build the API image and push it to a registry your cluster can pull from:

```sh
docker build --target api -t <registry>/octryx-api:<tag> .
docker push <registry>/octryx-api:<tag>
```

Then set `images.api.repository` and `images.api.tag` (or a `digest`). The chart refuses to render without
`images.api.repository`.

## Install

```sh
helm install octryx deployment/helm/octryx -n octryx -f my-values.yaml
```

`ingress.maxBodySize` (default `513m`) is the largest request body the ingress forwards, set as the ingress-nginx
annotation `proxy-body-size`. With another controller, set its equivalent in `ingress.annotations`.

## Server runners

`runners.enabled: true` runs the platform's server runners (`docker/runner`) next to the api: Codex sessions in pods
of their own, for chat turns and workflow steps "on the Server runners".

- Build and push the runner image (`docker build -f docker/runner/Dockerfile -t <registry>/octryx-runner:<tag> .`)
  and set `images.runner.repository` and `tag`.
- Add `RUNNER_JOIN_SECRET` (any long random value) to `existingSecret`. The api reads it, and each runner pod gets
  only that key as a file.
- The runner pods reach the platform only through `<release>-octryx-runner-gateway`, a small nginx that forwards to
  the api's port. With `runners.networkPolicy.enabled` (the default), a runner's egress is that gateway and the
  cluster DNS, and nothing reaches a runner. Your CNI must enforce NetworkPolicy; check that it does.
- The runner container starts as root, without any capability but CHOWN, FOWNER, FSETID, SETUID and SETGID. It uses
  them only to hand its writable places to the launcher and to the agent's account (`docker/runner/entry.sh`). The
  namespace therefore needs the Pod Security level `baseline`, not `restricted`.
- `runners.runtimeClassName` sets the pods' RuntimeClass, for example gVisor (`docker/runner/README.md`, "Container
  runtime"). The api admits only runners on that runtime; a missing class means no runner pod starts, and a pool
  turn answers `needs_configuration`.
- A runner's state (its device credential) lives in memory and goes with its pod: a new pod enrolls as a new device.

## Model provider egress

Every model call goes through the api's gateway; runners and devices never reach a provider. If the cluster restricts
egress, allow HTTPS (443) from the api pod to `api.anthropic.com` (Claude seat) and `chatgpt.com` (Codex seat), and
from the LiteLLM pod to the providers the Workspaces use (for example `bedrock-runtime.<region>.amazonaws.com`,
`api.openai.com`). Embeddings and rerank (Bedrock) and speech (OpenAI, ElevenLabs, AWS, Azure) are called by the api
directly, not through the gateway. A blocked seat route makes the run wait with `needs_configuration`
(`seat_upstream_unreachable`) instead of timing out.

## Resource names and the database volume

Resource names follow `<release>-octryx` (or `fullnameOverride`), and the internal database is called `octryx`
(or `database.name`). An upgrade keeps its resources and its database volume only under the names they already use:

- `fullnameOverride`: the resource prefix of the existing `<prefix>-postgres` StatefulSet. A different prefix makes
  Helm create a new StatefulSet with a new, empty volume.
- `database.name`: the database name in that volume.

## Packaging the chart

Both containment checks run first, from the repository root, and are not optional: `helm package` archives the
chart directory as it is on disk, including untracked and ignored files, so a package that skips them can leak secret
material. A non-zero exit means: do not package.

```bash
python3 scripts/check_release_values_secrets.py
python3 scripts/check_chart_package_inputs.py deployment/helm/octryx

cd deployment/helm
helm package octryx/
# optional, only to a registry you control:
# helm push octryx-*.tgz oci://<registry>/helm-charts
```

`scripts/local-build-push.sh` does the same for all images and the chart (both checks first) and pushes them to your
own registry; it needs `OCTRYX_REGISTRY`, `OCTRYX_IMAGE_BASE`, `OCTRYX_HELM_OCI_REPO` and `OCTRYX_REGISTRY_USER`
(optional `OCTRYX_REGISTRY_TOKEN`) and has no defaults.

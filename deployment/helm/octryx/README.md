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

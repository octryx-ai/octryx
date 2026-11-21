{{/* Release-scoped name prefix: "<release>-octryx", or the release name if it already says so. */}}
{{- define "octryx.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 50 | trimSuffix "-" -}}
{{- else if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "octryx.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* Selector labels of one component: (dict "root" . "component" "api"). */}}
{{- define "octryx.selector" -}}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* repository@digest when a digest is pinned, else repository:tag. */}}
{{- define "octryx.image" -}}
{{- $repository := required "set images.api.repository to the image you built and pushed" .repository -}}
{{- if .digest -}}
{{ $repository }}@{{ .digest }}
{{- else -}}
{{ $repository }}:{{ .tag | default "latest" }}
{{- end -}}
{{- end -}}

{{- define "octryx.secretName" -}}
{{- required "existingSecret is required: create the Secret first (see https://octryx.ai/docs/install/kubernetes)" .Values.existingSecret -}}
{{- end -}}

{{- define "octryx.serviceAccountName" -}}
{{- .Values.serviceAccount.name | default (include "octryx.fullname" .) -}}
{{- end -}}

{{- define "octryx.podSecurity" -}}
runAsNonRoot: true
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "octryx.containerSecurity" -}}
allowPrivilegeEscalation: false
capabilities:
  drop: ["ALL"]
{{- end -}}

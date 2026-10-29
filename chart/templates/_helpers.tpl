{{- define "simcrew.name" -}}
{{- .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "simcrew.fullname" -}}
{{- if contains .Chart.Name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "simcrew.labels" -}}
app.kubernetes.io/name: {{ include "simcrew.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "simcrew.selectorLabels" -}}
app.kubernetes.io/name: {{ include "simcrew.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "simcrew.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "simcrew.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "simcrew.postgresqlName" -}}
{{- printf "%s-postgresql" (include "simcrew.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "simcrew.postgresqlSelectorLabels" -}}
app.kubernetes.io/name: {{ include "simcrew.name" . }}-postgresql
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* Reuse the stored password on upgrade so the database stays reachable. */}}
{{- define "simcrew.dbPassword" -}}
{{- if .Values.postgresql.auth.password }}
{{- .Values.postgresql.auth.password }}
{{- else }}
{{- $existing := lookup "v1" "Secret" .Release.Namespace (include "simcrew.fullname" .) }}
{{- if and $existing $existing.data (hasKey $existing.data "POSTGRESQL_PASSWORD") }}
{{- index $existing.data "POSTGRESQL_PASSWORD" | b64dec }}
{{- else }}
{{- randAlphaNum 24 }}
{{- end }}
{{- end }}
{{- end }}

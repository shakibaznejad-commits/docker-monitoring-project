# Monitoring publication plan

Goal: reproducible infrastructure/application dashboards and actionable alerts, preserving existing services and data.

Architecture: retain Compose topology and external network; use service DNS for FastAPI discovery. Provision a stable Prometheus datasource, two dashboards, and Grafana-managed alerts. Keep notification policies and contact points under operator control to preserve existing email routing.

- [x] Add contract tests for dashboard coverage, datasource references, application targets, and secret exclusion; confirm missing provisioning fails.
- [x] Add provisioning and safe environment example; preserve existing Grafana volume and SMTP compatibility.
- [x] Validate Compose for both repositories, Prometheus configuration/expressions and Grafana startup in isolated containers; exercise live FastAPI scrapes and alert evaluation.
- [x] Document setup, thresholds, recovery, verification, and platform limitations.
- [x] Review changes and staged secrets.

Publication procedure: commit and push the current branch only after the final live test exits successfully.

Execution: inline, as requested by the user's autonomous-work instruction. No existing volumes will be removed or reset. No reverse-proxy source changes are expected.

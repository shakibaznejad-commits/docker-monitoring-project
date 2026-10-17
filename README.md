# Docker Monitoring & Observability

A hands-on monitoring stack for a Dockerized, multi-service application, built with **Prometheus**, **Grafana**, **Node Exporter**, and **cAdvisor**. It monitors two FastAPI services running behind an Nginx reverse proxy in a separate Docker Compose project.

## Features

- **Service monitoring:** Prometheus scrapes `/metrics` from two FastAPI applications (`service-a` and `service-b`).
- **Application metrics:** HTTP request counters, response status codes, and request-duration histograms.
- **Infrastructure metrics:** Host metrics from Node Exporter and container metrics from cAdvisor.
- **Grafana dashboards:** Request rate, P95 latency, HTTP error rate, and side-by-side comparisons of the two services.
- **Alerting:** A Grafana alert for HTTP 5xx responses from Service A, with email notifications configured locally via SMTP.
- **Persistent Grafana data:** A Docker volume stores Grafana configuration and dashboard state.

## Architecture

```text
                  Client
                    |
             localhost:8080
                    |
             Nginx Reverse Proxy
                /         \
          /users           /cv
             |               |
        FastAPI A        FastAPI B
          :8000            :8000
             \               /
              \   /metrics  /
               \     |     /
                 Prometheus <----- Node Exporter
                  :9090      <----- cAdvisor
                    |
                  Grafana
                   :3000
                Dashboards
                + Alerts
```

The application and monitoring stacks run in **separate Docker Compose projects** and communicate over a shared external Docker network named `monitoring-network`.

## Related project

The monitored application stack is maintained in a separate repository:

**[Docker Nginx Reverse Proxy](https://github.com/shakibaznejad-commits/docker-nginx-reverse-proxy)**

Clone both repositories to run the complete demonstration.

## Requirements

- Docker Engine / Docker Desktop with Docker Compose
- Git
- Free local ports: `3000`, `8080`, `8082` (loopback), `9090`, and `9100`

## Getting started

### 1. Clone both repositories

```bash
 git clone https://github.com/shakibaznejad-commits/docker-nginx-reverse-proxy.git
 git clone https://github.com/shakibaznejad-commits/docker-monitoring-project.git
```

### 2. Create the shared Docker network

```bash
 docker network create monitoring-network
```

If the network already exists, skip this step.

### 3. Start the reverse proxy application

```bash
 cd docker-nginx-reverse-proxy
 docker compose up -d --build
```

**Note:** The reverse proxy project's Compose file must attach `service-a` and `service-b` to the external `monitoring-network` for Prometheus to reach them.

### 4. Configure Grafana email (optional)

In the monitoring repository, create a local `.env` file for the SMTP variables referenced by the Compose configuration:

```dotenv
GRAFANA_SMTP_USER=your-email@example.com
GRAFANA_SMTP_PASSWORD=your-app-password
```

Do not commit `.env` or any real credentials to Git. Email alert delivery requires a valid SMTP setup in the Grafana service configuration.

### 5. Start monitoring

```bash
 cd ../docker-monitoring-project
 docker compose up -d
```

### 6. Open the tools

| Tool | Local URL |
| --- | --- |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Node Exporter | http://localhost:9100/metrics |
| Reverse Proxy | http://localhost:8080 |
| cAdvisor | http://localhost:8082 (bound to loopback) |

In Prometheus, visit **Status → Target health** (or `/targets`) and verify that the targets are **UP**.

> **Dashboard note:** The Grafana dashboard and email alert were created through the Grafana UI during development. Unless dashboard provisioning files or an exported dashboard JSON are added to this repository, they will **not automatically appear on a fresh installation**.

## Example PromQL queries

**Service availability (scrape success)**

```promql
up{job=~"service-a|service-b"}
```

**Request rate by service**

```promql
sum by (job) (rate(requests_total{job=~"service-a|service-b"}[5m]))
```

**P95 request duration (milliseconds)**

```promql
histogram_quantile(
  0.95,
  sum by (job, le) (
    rate(http_request_duration_seconds_bucket{job=~"service-a|service-b"}[5m])
  )
) * 1000
```

**HTTP 4xx + 5xx error percentage**

```promql
100 *
(
  sum by (job) (
    rate(http_responses_total{job=~"service-a|service-b",status_code=~"4..|5.."}[5m])
  )
  or on(job)
  (
    0 * sum by (job) (
      rate(http_responses_total{job=~"service-a|service-b"}[5m])
    )
  )
)
/
clamp_min(
  sum by (job) (
    rate(http_responses_total{job=~"service-a|service-b"}[5m])
  ),
  1e-12
)
```

**Service A HTTP 5xx alert expression**

```promql
sum(increase(http_responses_total{job="service-a",status_code=~"5.."}[5m])) or vector(0)
```

## Notes and limitations

- `up = 1` means Prometheus successfully scraped the target; it is **not** a full application health check.
- `rate()` and `increase()` use time windows, so an old error can remain in a cumulative counter while its recent error rate returns to zero.
- The P95 histogram resolution depends on the configured histogram buckets.
- Container names in `prometheus/prometheus.yml` are tied to the Compose project/container naming used during development. Update scrape targets if your actual container names differ.
- SMTP credentials and locally created Grafana dashboards are not intended to be stored as secrets or automatically reconstructed from this README.

## License

No license is specified in this repository unless a `LICENSE` file is added.

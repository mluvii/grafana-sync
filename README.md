# Synchronization script for mluvii statistics and an grafana instance

## Description

This script can be used to synchronize mluvii company settings with grafana organization.

Synchronized items:
* organization
* users
* data source (InfluxDB)
* home dashboard containing links to configured dashboards
  * requires [scripted dasboard](https://grafana.com/docs/grafana/latest/dashboards/scripted-dashboards/)

## Deployment

### Kubernetes CronJob

```
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: grafana-sync
spec:
  schedule: "0 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: grafana-sync
              image: mluvii/grafana-sync:latest
              imagePullPolicy: Always
              env:
                - name: GRAFANA_URL
                  value: "..."
                - name: GRAFANA_USER
                  value: "..."
                - name: GRAFANA_PASS
                  valueFrom:
                    secretKeyRef:
                      name: ...
                      key: ...
                - name: MLUVII_DOMAIN
                  value: "..."
                - name: MLUVII_CLIENT_ID
                  value: "..."
                - name: MLUVII_CLIENT_SECRET
                  valueFrom:
                    secretKeyRef:
                      name: ...
                      key: ...
          restartPolicy: OnFailure
```

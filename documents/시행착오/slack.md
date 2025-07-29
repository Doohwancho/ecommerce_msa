# slack에 incoming webhook

doohwancho1993@gmail.com 으로 접속

하는법: https://velog.io/@yujinaa/Slack-Incoming-Webhook-%EC%97%B0%EB%8F%99%ED%95%B4%EC%84%9C-%EC%95%8C%EB%A6%BC%EB%B3%B4%EB%82%B4%EA%B8%B0

1. webhook URL

- https://hooks.slack.com/services/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

2. 수신 웹후크 URL

- https://hooks.slack.com/services/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

```bash
# window terminal 기준,
curl -X POST -H "Content-Type: application/json" --data "{\"channel\": \"#새-채널\", \"username\": \"테스트봇\", \"text\": \"Windows 명령 프롬프트에서 보내는 테스트 메시지입니다. 🚀\", \"icon_emoji\": \":ghost:\"}" "https://hooks.slack.com/services/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"
```

3. slack channel '#alerts', '#alerts-critical' 채널 만들기 (alertManager에서 이 채널로 메시지 보낼 예정)

# alert rules

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-rules
data:
  rules.yml: |
    groups:
    - name: kubernetes-workload-alerts
      rules:
      # --- 워크로드 상태 알람 ---
      # Observability 중요성: Pod의 비정상 상태를 가장 먼저 감지하여 서비스 중단으로 이어지기 전에 조치할 수 있게 합니다.
      # CrashLoopBackOff는 애플리케이션 자체의 버그나 설정 오류일 가능성이 높습니다.
      - alert: KubePodCrashLooping
        expr: rate(kube_pod_container_status_restarts_total[5m]) * 60 * 5 > 3
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Pod가 계속 재시작됩니다 ({{ $labels.namespace }}/{{ $labels.pod }})"
          description: "{{ $labels.pod }} 파드가 지난 5분 동안 3번 이상 재시작되었습니다. 애플리케이션 로그를 확인하세요."

      # Observability 중요성: 배포된 레플리카 수가 의도한 수와 다를 경우, 스케일링 문제나 Pod 생성 실패를 의미합니다.
      # 이는 사용자가 직접적으로 서비스 품질 저하를 느끼게 되는 상황입니다.
      - alert: KubeDeploymentReplicasMismatch
        expr: kube_deployment_spec_replicas != kube_deployment_status_replicas_available
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Deployment 레플리카 수가 맞지 않습니다 ({{ $labels.namespace }}/{{ $labels.deployment }})"
          description: "의도한 레플리카 수({{ `{{ kube_deployment_spec_replicas{deployment=\"$labels.deployment\"} | query | first | value }}` }})와 실제 가용한 레플리카 수({{ `{{ $value }}` }})가 다릅니다."

      # Observability 중요성: DaemonSet은 로깅, 모니터링 에이전트 등 클러스터의 필수 기능을 담당합니다.
      # DaemonSet Pod가 특정 노드에서 실행되지 않으면 해당 노드는 관리 사각지대에 놓이게 됩니다.
      - alert: KubeDaemonSetNotReady
        expr: kube_daemonset_status_desired_number_scheduled != kube_daemonset_status_number_ready
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "DaemonSet이 일부 노드에서 준비되지 않았습니다 ({{ $labels.namespace }}/{{ $labels.daemonset }})"
          description: "의도한 DaemonSet 수({{ `{{ kube_daemonset_status_desired_number_scheduled{daemonset=\"$labels.daemonset\"} | query | first | value }}` }})와 실제 준비된 수({{ `{{ $value }}` }})가 다릅니다."

    - name: kubernetes-resource-alerts
      rules:
      # --- 리소스 관련 알람 ---
      # Observability 중요성: CPU/메모리 같은 자원 고갈은 시스템 전체의 성능 저하와 장애의 직접적인 원인입니다.
      # 임계치 기반 알람은 가장 기본적인 예방 조치입니다.
      - alert: KubePodHighCPUUsage
        expr: (sum(rate(container_cpu_usage_seconds_total{container!=""}[5m])) by (namespace, pod) / sum(kube_pod_container_resource_limits{resource="cpu"} > 0) by (namespace, pod)) * 100 > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Pod CPU 사용량 높음 ({{ $labels.namespace }}/{{ $labels.pod }})"
          description: "{{ $labels.pod }} 파드의 CPU 사용량이 5분 동안 80%를 초과했습니다. (현재 값: {{ `{{ $value | printf \"%.2f\" }}` }}%)"

      # Observability 중요성: PVC가 Pending 상태에 머무는 것은 Stateful 애플리케이션이 스토리지를 할당받지 못해 시작조차 못하고 있음을 의미합니다.
      # 사용자는 서비스가 다운된 것으로 인지하지만, Pod는 Crash 상태가 아니므로 놓치기 쉽습니다.
      - alert: KubePersistentVolumeClaimPending
        expr: kube_persistentvolumeclaim_status_phase{phase="Pending"} == 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "PersistentVolumeClaim이 Pending 상태입니다 ({{ $labels.namespace }}/{{ $labels.persistentvolumeclaim }})"
          description: "PVC {{ $labels.persistentvolumeclaim }}가 5분 이상 Pending 상태입니다. StorageClass나 가용 PV를 확인하세요."

    - name: kubernetes-cluster-health-alerts
      rules:
      # --- 클러스터 상태 알람 ---
      # Observability 중요성: 노드 장애는 해당 노드에서 실행 중인 모든 서비스의 장애를 의미하며, 클러스터 전체의 가용성에 큰 영향을 줍니다.
      # 즉각적인 조치가 필요한 가장 심각한 수준의 알람입니다.
      - alert: KubeNodeNotReady
        expr: kube_node_status_condition{condition="Ready", status="true"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "노드가 NotReady 상태입니다 ({{ $labels.node }})"
          description: "{{ $labels.node }} 노드가 1분 이상 NotReady 상태입니다. Kubelet 상태나 네트워크를 확인하세요."

      # Observability 중요성: 모니터링 시스템 자체의 장애는 모든 관측 가능성을 잃는 것을 의미합니다.
      # '감시자를 감시'하는 것은 안정적인 운영의 기본입니다.
      - alert: KubeStateMetricsDown
        expr: up{job="kube-state-metrics"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "kube-state-metrics가 다운되었습니다"
          description: "핵심 메트릭을 수집하는 kube-state-metrics가 응답하지 않습니다. 모니터링 시스템을 점검하세요."

    - name: testing-alerts
      rules:
      # --- 파이프라인 테스트용 알람 ---
      # expr: vector(1) 은 항상 참(true)인 값을 반환하여, 이 알람을 즉시 Firing 상태로 만듭니다.
      # 이를 통해 다른 조건 없이 Prometheus -> Alertmanager -> Slack 알람 파이프라인이
      # 정상적으로 동작하는지 확인할 수 있습니다.
      - alert: TestAlert
        expr: vector(1)
        labels:
          severity: warning # 'slack-default' receiver로 라우팅되도록 warning으로 설정
        annotations:
          summary: "✅ 테스트 알람입니다."
          description: "이 메시지가 보인다면, Prometheus -> Alertmanager -> Slack 파이프라인이 정상적으로 동작하는 것입니다."
```

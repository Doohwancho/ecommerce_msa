# A. 그냥 prometheus vs opentelemetry -> prometheus

## 1. 초기생각: 로깅, 백트레이싱도 opentelemetry 거쳤으니까, apm도 open telemetry 거치는게 좋지 않을까?

apm metric도 표준화 해서 시각화 하고 보관하는거지

## 2. 문제

### 2-1. otel과 prometheus에서 수집하는 메트릭 레이블링의 이름과 단위가 다르다.

fastapi에 경우, 이 두 모듈로 메트릭 수집을 한다.

```
opentelemetry-instrumentation-fastapi==0.46b0
opentelemetry-instrumentation-system-metrics==0.46b0
```

프로메테우스 metrics explorer에서 보면

```
http_server_active_requests
http_server_duration_milliseconds_bucket
http_server_duration_milliseconds_count
http_server_duration_milliseconds_sum
http_server_response_size_bytes_bucket
http_server_response_size_bytes_count
http_server_response_size_bytes_sum
process_runtime_cpython_context_switches_total
process_runtime_cpython_cpu_time_seconds_total
process_runtime_cpython_cpu_utilization_ratio
process_runtime_cpython_gc_count_bytes_total
process_runtime_cpython_memory_bytes
process_runtime_cpython_thread_count
scrape_duration_seconds
scrape_samples_post_metric_relabeling
scrape_samples_scraped
scrape_series_added
system_cpu_time_seconds_total
system_cpu_utilization_ratio
system_disk_io_bytes_total
system_disk_operations_total
system_disk_time_seconds_total
system_memory_usage_bytes
system_memory_utilization_ratio
system_network_connections
system_network_dropped_packets_total
system_network_errors_total
system_network_io_bytes_total
system_network_packets_total
system_swap_usage_pages
system_swap_utilization_ratio
system_thread_count
up
```

여기서 앞단에 `http_server_` 붙은건 `opentelemetry-instrumentation-fastapi`가 측정하고,
나머지 `system_` 붙은거나 `process_` 붙은건 `opentelemetry-instrumentation-system-metrics`가 측정한다.

system-metrics 모듈은 cpu/memory 사용량 같은 메트릭 측정하고,
fastapi 모듈은 웹단에서 요청 초당 얼마나 왔고, 500 에러 얼마나 뱉었고 등을 측정한다.

문제는 open telemetry 모듈이 측정하고 opentelemetry 를 한번 거칠 때, 데이터 레이블링 작업을 하는데,
변수명이라던가 등이 prometheus가 하는거랑 완벽하게 일치하지 않는다.

예를들어, otel에서는 `http_server_duration_milliseconds_...` 이렇게 표기하는데, prometheus에서는 `http_requests_latency_seconds_...` 이렇게 표기하고 단위도 second to mili-second으로 다르다.

### 2-2. prometheus에는 수집하는 메트릭이 otel에서는 빠질 가능성도 존재한다.

예를들어 prometheus metric 수집기에는 있는 `http_requests_total`가 otel-prometheus에서는 없고, http_server_duration_milliseconds_count 라는 히스토그램(Histogram)의 일부로 포함한다고 한다.

http_server_duration_milliseconds 히스토그램은 내부에 \_sum(총합), \_count(횟수), \_bucket(분포)을 모두 가지고 있습니다. 여기서 \_count가 바로 요청 횟수 역할을 한다고 한다.

이 말은 즉, grafana custom dashboard를 만들어야 하고, 저거 일일히 다 고려해서 만들어야 한다는 것.

또한 이게 이름만 다른건지, 아니면 prometheus에서 수집하는 메트릭이 있는데 otel에서는 빠진건지 하나하나 다 비교해봐야 한다.

### 2-3. 버전 수정의 위험성

현재 버전은

```requirements.txt
opentelemetry-api==1.25.0
opentelemetry-sdk==1.25.0
opentelemetry-exporter-otlp==1.25.0

opentelemetry-instrumentation==0.46b0
opentelemetry-instrumentation-fastapi==0.46b0
opentelemetry-instrumentation-grpc==0.46b0
opentelemetry-instrumentation-pymongo==0.46b0
opentelemetry-instrumentation-logging
opentelemetry-instrumentation-system-metrics==0.46b0
opentelemetry-semantic-conventions==0.46b0
```

1.25.0 에 0.46b0 버전인데, 원래는 1.21.0 버전에 0.42b0버전이었다.

왜 올렸냐면 `opentelemetry-instrumentation-system-metrics==0.42b0` 의 시스템 메트릭 수집은 잘 됬는데,\
`opentelemetry-instrumentation-fastapi==0.42b0`의 fastapi 메트릭 수집은 안됬기 때문이다.

삽집해봤는데 결국 버전 올리니까 해결됬다.

문제는 기존에 1.21.0 / 0.42b0 버전에 맞게 백트레이스랑 로깅 설정 세팅 다 해놨는데, apm 때문에 설정잡은게 깨질 위험이 있었다.

### 2-4. msa apm 전용 istio_metrics 들도 otel 통해서 보낼꺼야?

## 3. 해결방안

### 3-1. 버전 올리고 로깅 / 백트레이스 충돌 잡고, prometheus metric labeling / 단위 맞춰서 grafana custom dashboard 제작하기

grafana dashboard hub에서 open telemetry 검색하면 나오는게, open telemetry를 한번 거친 서버의 메트릭이 아니라,

otel 서버 그 자체의 apm을 모니터링하는 대쉬보드이고,

fastapi 전용 dashboard 를 열면 죄다 no data 뜨는데, 변수명 안맞아서다.

msa니까 observability를 위해 추후 istio metrics도 모니터링 한다고 하면, 이것도 같은 문제 겪을 것으로 예상된다.

### 3-2. APM은 opentelemetry 거치지 않고 바로 prometheus + grafana 쓰기

이게 편한 길인 듯 싶다.

# B. k8s에서 prometheus + grafana로 APM하기

```bash
kubectl apply -f k8_configs/kube-state-metrics.yaml
kubectl apply -f k8_configs/prometheus-rbac.yaml
kubectl apply -f k8_configs/prometheus-configmap.yaml
kubectl apply -f k8_configs/prometheus-deployment.yaml

kubectl port-forward prometheus-64bcdcb847-6lwqh 9090:9090
http://localhost:9090/

kubectl apply -f k8_configs/grafana.yaml
kubectl port-forward svc/grafana 3000:3000
http://localhost:3000
```

1. admin admin 로그인 후 왼쪽 메뉴의 Connections → Data sources로 이동하면,
2. 이미 추가된 default prometheus datasource 사용하지 말고, 새로 datasource -> prometheus -> 서버 url에
   http://prometheus-service:9090 입력
3. 전체 k8s cluster 모니터링용은 id: 15661

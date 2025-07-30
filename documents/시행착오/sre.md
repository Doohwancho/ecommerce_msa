# 4 golden signal

## 0. 결론

- 1 & 2는 과거지표 나타내는 성적표, 이걸 고객에게 보여주면서 앞으로 99.95% 달성하겠습니다! 하는 것
- 3 & 4는 '지금당장' 무슨일이 일어나고 있는지, 장애에 대응하거나 서버를 증설해야 할지 판단하는 현재 지향적인 계기판

## 1. 가용성 (Availability) & 에러 (Errors)

목표: 전체 요청 중 실패한 요청(5xx 에러)의 비율을 실시간으로 확인.

```promql
# case1) 실시간 - 5분 동안의 전체 요청 대비 5xx 에러 비율 계산
# 목적: 지금 당장 서비스가 터졌는지 아닌지를 빨리 알아채기
(
	sum(rate(http_requests_total{job="kubernetes-pods", code=~"5.."}[5m])) or
  vector(0)
)
/ sum(rate(http_requests_total{job="kubernetes-pods"}[5m]))


# case2) 28일간의 전체 가용율, availability (SLO 측정용)
# 목적: SRE가 분기나 월말에 "우리 이번 달 목표 99.9% 지켰냐?" 보고할 때 쓰는 거.
# rate() 대신 increase()를 썼는데, 이건 '초당 평균'이 아니라 '기간 내 총 증가량'을 보여줌. 보고서에는 총량이 더 적합함.

1 - (
	sum(increase(http_requests_total{job="kubernetes-pods", code=~"5.."}[28d])) or
  vector(0)
)
/ sum(increase(http_requests_total{job="kubernetes-pods"}[28d]))
```

추천 그래프: gauge(99.9%) or time series(시간에 따른 에러율 보여줌)

## 2. 지연 시간 (Latency)

목표: "99.9%의 시간 동안, 5분 단위 p95 응답 시간이 200ms 목표를 만족해야 한다."

```PromQL:
#5 분 동안의 95th percentile latency 계산 (단위: 초)
histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="kubernetes-pods"}[5m])) by (le))
```

설명: histogram_quantile() 함수가 핵심. 0.95는 95%를 의미함. 히스토그램 버킷 데이터를 기반으로 "상위 5%를 제외한 나머지 요청은 몇 초 안에 처리됐나?"를 계산해 줌.

```PromQL:
#5 분 동안의 95th percentile latency 계산 (단위: 초)
histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="kubernetes-pods"}[5m])) by (le))

# 28일 동안, 5분 단위 p95가 200ms(0.2초) 목표를 지킨 시간의 비율
avg_over_time(
  (
    histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="kubernetes-pods"}[5m])) by (le)) < 0.2
  )[28d:1m]
)
```

추천 그래프:

- Time series: p50, p90, p95, p99 등 여러 지연 시간 지표를 여러 선으로 그려서 같이 보면 좋음.

* thresh hold 200ms, 95%의 http 요청에 대하여, 빨간색 horizontal line,
* grid는 0~1000(ms)

## 3. 트래픽 (Traffic)

목표: 서비스가 초당 처리하는 요청 수(RPS, Requests Per Second)를 확인.

```PromQL:
# 5분 동안의 초당 평균 요청 수 (RPS)
sum(rate(http_requests_total{job="kubernetes-pods"}[5m]))
```

설명: http_requests_total이라는 카운터가 얼마나 빠르게 증가하는지를 rate() 함수로 계산해서 현재 트래픽을 보여줌.

추천 그래프:

- Time series: 시간에 따라 트래픽이 어떻게 변하는지(피크 시간 등)를 보기에 가장 적합함.

---

1. availability & error 랑 2. latency는 한달동안 평균 얼마에 목표 얼마에 99.9% 달성햇다 이런식으로 말이 가능한데,
2. 트래픽은 걍 실시간으로 요청이 얼마나 몰리는지 반응하는걸 보는게 목적이라 최근 5분꺼만 보는거구나

## 4. 포화도 (Saturation)

목표: 시스템의 주요 자원(CPU, 메모리)이 얼마나 한계에 가까워졌는지 확인.

```PromQL:
# 5분 동안의 평균 CPU 사용률 (%)
# node_exporter를 사용한다고 가정
100 * (1 - avg(rate(node_cpu_seconds_total{job="my-node-exporter", mode="idle"}[5m])))
```

설명: 전체 CPU 시간 중 아무것도 안 하고 노는 시간(idle)의 비율을 구한 뒤, 1에서 빼서 실제 사용률을 계산함.

```PromQL (메모리 사용률 예시):

# 현재 메모리 사용률 (%)
100 * (1 - (node_memory_MemAvailable_bytes{job="my-node-exporter"} / node_memory_MemTotal_bytes{job="my-node-exporter"}))
```

설명: 전체 메모리 중 사용 가능한 메모리를 제외한 비율을 계산함.

추천 그래프:

- Gauge: 현재 사용량을 0-100% 사이의 계기판으로 보여주기에 가장 직관적임.
- Time series: 시간에 따른 자원 사용량 변화를 추적해 장애를 예측하는 데 씀.

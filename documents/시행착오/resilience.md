
# J. k8s container의 안정성을 높히는 방법은?
>Q. reliability(안정성)을 높히기 위해 무얼 할 수 있을까?

## j-1. mysql 
### j-1-1. HA 
node가 1개면 db가 죽었을 때, 서버 전체 장애로 퍼지니까,\
node 3개 (1 master 2 read replica)로 나눈 HA구성한다.


### j-1-2. 자동 failover 처리
일단 failover란, mysql pod가 하나 죽었을 때, 재시작 후, master-slave cluster에 re-join 시키는 것이다.\
reliability 높히는데 매우 중요하다.

처음엔 수동으로 클러스터 생성해서 master/slave node를 수동으로 join 해 보았다.\
read 요청과 CUD 요청이 나뉘어져서 처리되는 기능은 잘 동작하였으나,\
문제는 mysql pod가 fail한 후에, k8s가 restart한 후, 기존 클러스터에 자동 re-join시켜주지 않았다.\
이걸 bash 스크립트로 pod 재시작 시에, cluster 정보 요청 후, 받아와서 어떤 mysql 접속하는 툴을 써서 re-join하는 요청을 날리는데, 안될경우 몇초 시다렸다가 retry 하고...\
이런걸 해봤는데 잘 안되서 몇일 날렸다. (documents/시행착오/mysql.md 에 대략적 내용 수록함)

찾아보니 InnoDB Cluster & mysql router for k8s setting가 공식문서에 있길래 참고해서 만들었다.\
이 세팅의 장점은 HA구성에서 pod하나가 죽으면, 나머지 pod끼리 쿼럼(재투표)해서 master를 재선출 하고,\
죽은 pod가 restart하면 자동으로 cluster.rejoin() 한다는 것이다. 


### j-1-3. 쿼럼?
- 쿼럼(과반수) 원칙: node가 죽어도 되는데, 어쨌든 살아있는 노드가 전체 노드 갯수의 절반+1(과반수) 이상이어야 한다.
- 예를들어 원래 2개에서 1개 장애나서 1개만 남으면, 기존의 전체 노드 갯수(2)의 과반수 1개 이상이 아니기 때문에 과반수 투표 못함 -> 자동 fail over 장애 조치 못한다.
- 근데 node 3개면, 1개 장애나도, 남은 2개가 기존 3개의 과반수 이상이기 때문에, 과반수 투표해서 primary / secondary 정해서 자동 fail over 장애 조치 된다.
- node를 4개로 할 수도 있긴 한데, failover 관점에서는 약간 비효율이다.
  - 1개 장애났을 때, 과반수 투표로 1개 primary, 2개 read replica로 설정할 수 있지만,
  - 2개 장애났을 때, 과반수 투표를 못하기 때문에, node가 3개던 4개던, 장애 감당 가능한 노드 최대 갯수는 1개 뿐이다.
  - 반면 node가 5개로 시작하면 2개까지 장애나도 3개가 남아 여전히 과반수 투표하여 자동 fail over 처리 가능하다.
  - 따라서 장애 자동 처리 때문에 노드 갯수는 3,5,7 등 홀수개가 추천된다.

---
ex) mongodb cluster 구성을 잠깐 보면, `mongo-stateful-0`에서 replica set을 초기화 한 다음, 상태를 보면,
```json
rs0 [direct: primary] test> rs.status()
{
  set: 'rs0',
  date: ISODate('2025-05-06T07:02:53.226Z'),
  myState: 1,
  term: Long('124'),
  syncSourceHost: '',
  syncSourceId: -1,
  heartbeatIntervalMillis: Long('2000'),
  majorityVoteCount: 2,
  writeMajorityCount: 2,
  votingMembersCount: 3,
  writableVotingMembersCount: 3,
  ...
```
총 노드가 2개니까, 과반수 2가 `majorityVoteCount`이고,\
replica set에 노드가 3개 있으니까 `votingMembersCount`가 3인걸 확인할 수 있다.


## j-2. mongodb 
### j-2-1. HA
몽고db도 mysql과 마찬가지로 reliability 확보 위해 HA구성한다. 

### j-2-2. mongodb HA 및 장애복구 시나리오
mysql cluster의 failover와 원리는 같다.\
mongodb cluster의 failover 처리는 mysql cluster 구성에 비해 비교적 수월했다.


## j-3 opentelemetry
### j-3-1. why1 - 표준의 중요성1
개발할 때 머리 깨지는 부분이 "표준을 어떻게 설계하지?" 이다.\
"표준"이라는건 그 위에 올라오는 것들의 기반이 되기 때문에, 한번 정해지면 나중에 바꾸기도 어렵다.\
그래서 개발하기 전에 시니어 분들이 모여서 표준부터 잡는다고 알고있다.

당장 '로깅을 어떻게 하지?' 생각 하면서 구글링 해봐도\
개발자마다, 회사마다 로깅할 때 어떤 정보를 넣는지 디테일들이 조금씩 다르다.\
로깅 디자인 하는 법같은거 찾아봐도 좋은 내용이긴 한데 서로 하는 말이 조금씩 다르다.

회사에서 개발자들끼리 머리 맞대서 로깅 표준 만들었다고 치자.\
loki 같은걸로 로그수집 한다고 하자.\
시간이 흘러 loki가 유료화 되었든, 다른 더 좋은걸로 migration 하든,\
다른 로그 플렛폼으로 바꿨는데 표준이 안맞는다면?

### j-3-2. why2 - 표준의 중요성2  
백트레이싱으로 jaeger를 쓴다고 치자.\
jaeger 코드가 app code 사이에 생각보다 많이 들어간다.\
시간이 흘러서 jaeger -> 다른 툴로 migration 한다고 치자.\
그러면 app code에 있는 그 많은 jaeger 코드 다 들어내야 한다. 복잡해진다.

반면 open-telemetry를 썼다면 otel.yaml 파일에서 jaeger -> 다른 툴로 바꿔주기만 하면 끝난다.


## j-4. jaeger
### j-4-1. why 
msa가 여러 모듈로 쪼개져있다보니,\
create_order() 만 하더라도 `order_module -> user_module & product_module -> payment_module -> order_module -> product_module` 

이렇게 왔다갔다해서, 
1. latency 측정도 정확히 어느 구간에서 병목이 걸리는지
2. 에러가 났으면, 저 4모듈중에 정확히 어느 모듈에서 난건지

파악하기 어려운데,\
이걸 파악시켜주는게 backtracing 기술이고, jaeger는 opensource backtracer이다.

![](./documents/images/jaeger1.png)
특정 `create_order`요청에 대해서 
1. latency 분포도 그려주고
2. 장애난 요청(빨간 점)이 어느 요청인지 알려준다. 

![](./documents/images/jaeger2.png)
1. 각 구간별로 latency가 얼마나 걸렸는지 확인할 수 있다.
2. 왼쪽 빨간색 느낌표가 장애난 부분이다. 

![](./documents/images/jaeger3.png)
3. 장애난 부분을 클릭해보면, 에러로그까지 확인할 수 있다. 


### j-4-2. context propagate
![](./documents/images/jaeger2.png)

create_order()이 여러 모듈과 통신한다고 했는데, 막상 보면, `fastapi-order-service`밖에 보이지 않는다. 

왜냐?

module을 넘나들 때, context 정보를 넘겨줘야 하기 때문이다.

이 부분이 grpc통신처럼 바로 왔다갔다하는 통신이면 그나마 괜찮은데,\
`order module -> mysql.outbox table -> debezium CDC -> kafka -> payment module`\
이런 식으로 비동기식 통신은 약간의 공식문서와의 씨름이 필요하다.

컨텍스트 정보를 잘넘겨주면, jaeger-ui가 다른 모듈들의 트레이싱 정보도 포함해서 보여주게 된다.

![](./documents/images/jaeger6.png)
`create_order()`안에 payment부분과 product 부분의 트레이스도 확인 가능하다.

![](./documents/images/jaeger7.png)
트레이스를 열어보면 세부정보도 확인할 수 있다.

![](./documents/images/jaeger8.png)
일부러 `create_order()`에 에러를 발생시키고

![](./documents/images/jaeger9.png)
에러 트레이스를 읽는 장면이다.


### j-4-3. debug
![](./documents/images/jaeger4-clock_skew.png)

module_a -> module_b로 context를 넘겨줄 때, id같은걸 공유하는데,\
jaeger가 트레이싱 정보를 재조합 하는 과정에서, id가 맞아도, 각자 트레이싱 정보의 시간이 너무나도 많이 차이나면, 이렇게 'time skew' warning을 뱉을 때가 있다. 

나의 경우엔...
![](./documents/images/resouce_is_full.png)
pod를 너무 많이 돌린게 원인...\
컴퓨터는 좋은걸 쓰자..

현재는 jaeger.yaml 설정에 트레이싱들의 시차가 크게 차이나도 무시하고 진행해줘! 라고 설정되 있는 상태이긴 하다.\
근데 시차 차이가 너무 나면, jaeger-ui상에서 분리된 모듈간 사이간격이 너무 떨어져있게 보여서(눈으로는) 약간 안이쁘긴 하다.

## j-5. resilience
### j-5-1. why 
msa에서 분리된 모듈중 하나가 장애가나면,\
그 모듈에 요청한 모듈이 무제한으로 기다리다가 트레픽 부하로 터지면, 연쇄적으로 다른 모듈들까지 장애가 전파되는 불상사가 생길 수 있다.

모듈끼리 통신할 땐, 
1. retry 몇번할껀지
2. 몇초 기다렸다 timeout처리 할건지 
3. 부하가 몰리면 퓨즈 내려버리는 circuitbreaker 
...을 미리 설정해둬야 분산시스템에서 장애전파를 방지할 수 있다.

### j-5-2. library 선택 기준
1. stars 수가 500이상에
2. 최근 반년 안에 maintained된 코드여야 한다.

### j-5-3. istio + envoy로 구현?
현업에서는 retry / timeout / circuit breaker 기능을 library보다는 istio + envoy로 구현한다고 한다.

왜냐하면
1. app code를 더럽히지 않고 인프라 레벨에서 기능 구현
2. circuit breaker의 경우 상태 정보라던지가 데이터로 남아 prometheus + grafana로 시각화 가능

그런데 문제는 istio & envoy가 조금 복잡하기도 하고,\
리소스를 많이 잡아먹는다고 한다.

![](./documents/images/resouce_is_full.png)

다음기회에...


### j-5-4. 자동복구

#### j-5-4-1. 헬스 체크 및 정상 종료 구현
1. `GET /health/live`로 컨테이너가 떴는지 확인하고
2. `GET /health/ready`로 fastapi가 각종 db와 연결 되었는지, config가 세팅 완료되었는지 확인한다.

이 health check가 컨테이너 복구의 기반이 된다.

이렇게 설정해놓으면, pod가 죽었을 때 k8s가 이 기능을 바탕으로 pod 재시작해준다.

## j-6. logging

### j-6-1. problem 
로깅 표준은 open telemetry로 맞췄는데,\
어디에 로그를 저장을 해야 잘 저장했다고 소문날까?

레거시 로깅 시스템 개선기같은 글을 보면, 쌓이는 양이 엄청 커서,\
나중에 크기가 어마어마해지면, 로그 query 한번에 10분이상씩 걸린다고 하더라.

### j-6-2. 해결책
위 요소를 고려했을 때,\
msa같이 잘게 쪼개놓으면 모듈별로 로그가 엄청 나올거고,\
ecommerce domain이라면 특히 payment관련 로그같은걸 query해볼 일이 자주 있을텐데,\
로깅 쿼리 속도가 중요하지 않을까?\
...라는 생각이 들어서 s3같은데 쌓아놓거나 다른 데이터베이스 말고\
검색속도가 특히 빠르고, 상세검색도 가능한 elastic search를 선택했다.\

![](documents/images/elastic_search-log-1.png)
_로그를 opentelemetry를 통해 elastic search에 쌓은걸 kibana로 시각화한 모습이다._

### j-6-3. 개선점 
막상 ecommerce platform인 배민의 로깅 개선기를 봤는데,\
ELK에서 단기 log는 loki에, 장기 log는 s3에 보관하도록 바꾸었더니,\
서버비가 약 20%정도 줄었다고 했다.

로키가 elastic search보다 full text 기반 query가 느리다곤 하나,\
어짜피 장기로그 보는 경우는 드물고,\
단기 로그 위주만 보는게 대부분인데,
단기 로그는 데이터 량이 얼마 없어서 쿼리속도가 빠를 것이기 때문에,\
elastic search보다 loki를 쓰는게 더 괜찮지 않나?\
배미급 회사에서 로그 서버비 23% 세이브는 꽤나 크기 때문에,\
다시 만들면 단기로그는 loki, 장기로그는 s3에 보관하는 식으로 만들지 싶다. 
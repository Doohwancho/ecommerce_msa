# index 
- step1. 단일 instance 
- step2. instance 2 (primary, secondary) 수동 배포 
- step3. HA: instance 3 (1 primary, 2 secondary), 수동 배포 
- step4. mysql InnoDB cluster & mysql-router w/ adminAPI 


# A. step1. 단일 instance 

# B. step2. instance 2 (primary, secondary) 수동 배포 
- 가장 minimal한 HA를 하기 위해서 1 primary, 1 secondary 구조를 선택
- node가 2개면 문제점이, node 1개가 죽어버리면, 재선거가 안됨. 서비스 중지됨. 최소 노드 갯수는 3개여야 함

#### B.1.5.2. deprecated) replica-set: primary-secondary
```bash
# Primary(mysql-0)가 시작된 후 복제 사용자를 생성해야 합니다.
kubectl exec -it mysql-0 -- bash

mysql -u root -p
# 암호 입력 (root)

# primary에서 복제 사용자 생성
CREATE USER 'replication'@'%' IDENTIFIED BY 'replication';
GRANT REPLICATION SLAVE ON *.* TO 'replication'@'%';
FLUSH PRIVILEGES;
```

mysql-0에서.. 
```bash
-- 바이너리 로그 활성화 확인
SHOW VARIABLES LIKE 'log_bin';
SHOW VARIABLES LIKE 'server_id';

-- 현재 바이너리 로그 파일과 위치 확인
SHOW MASTER STATUS;

+------------------+----------+--------------+------------------+-------------------+
| File             | Position | Binlog_Do_DB | Binlog_Ignore_DB | Executed_Gtid_Set |
+------------------+----------+--------------+------------------+-------------------+
| mysql-bin.000003 |     9276 |              |                  |                   |
+------------------+----------+--------------+------------------+-------------------+
1 row in set (0.00 sec)

...에서 mysql-bin.000003 을 복사!
position 9276도 복사!
```



mysql-1에서..
```bash
-- Primary 연결 설정
CHANGE MASTER TO
    MASTER_HOST='mysql-0.mysql-headless',
    MASTER_USER='replication',
    MASTER_PASSWORD='replication',
    MASTER_LOG_FILE='mysql-bin.000003',  -- Primary에서 확인한 값
    MASTER_LOG_POS=9276;                     -- Primary에서 확인한 값

-- 복제 시작
START SLAVE;

-- 복제 상태 확인
SHOW SLAVE STATUS\G
```

주의!
1. 현재 복제는 "현재 시점"부터 시작됩니다. 즉, MASTER_LOG_POS=9276 시점 이후의 변경사항만 복제됩니다.
2. 이전에 있던 데이터는 복제되지 않습니다.


---
```bash
# fastapi_module 에서 mysql 연결할 때,
- 쓰기 작업(CUD): `mysql-primary:3306` 또는 `mysql-0.mysql-headless:3306` 사용
- 읽기 작업(R): `mysql-secondary:3306` 또는 `mysql-1.mysql-headless:3306` 사용

아니면 환경변수 설정 
env:
- name: DB_WRITE_HOST
  value: mysql-primary
- name: DB_READ_HOST
  value: mysql-secondary
```
- 가장 basic한 모델 
- HA 및 자동 failover 구현하려고 instance 늘리고 router에서 w/r 구분해서 연결하기로 결정 

# C. step3. HA: instance 3 (1 primary, 2 secondary), 수동 배포 
- HA + 자동 failover 복구 되려면, 클러스터 만들고, 클러스터 안 최소 노드 갯수는 3개여야, 한개가 죽고 재선거 했을 때, primary 뽑고, secondary 뽑아서 primary-secondary 구조로 시스템이 유지됨
- 그러면서 죽은 pod가 다시 restart하면 기존 cluster에 rejoin하는 식으로 구현하려 했으나,
- mysql-0,1,2 노드 3개 만들고, mysql-router를 띄우고, 수동으로 터미널로 접속해서 cluster만들고 join시키고 통신시키는거 까진 성공시킴. 
- pod하나를 일부러 죽이고 cluster에 rejoin하는 것 까지 확인해서 자동 failover 기능이 되는 것 까지 확인했는데,
- 문제는, mysql-router가 죽었다가 재시작한 mysql pod를 연결 못하는 것이었다.
- failover가 자동으로 일어나야 하는데, 수동으로 cluster만들고 하는건 잘 안됬다. 몇일 태움. 
- arm64 아키텍처를 지원하는 mysql에서 mysql-shell 지원을 안해서 커스텀 이미지 말아올려서 쓰고 자동 failover 구현하려고 몇일 날림 아으 

### c-1. mysql과 mysql-shell이된 설치된 docker을 말아올리기 
```bash
cd mysql/

docker buildx build --platform linux/arm64 -t doohwancho/mysql-custom:8.0.29 --push .
```

### c-2. mysql group replication setting (1 primary, 2 secondary)
```bash
# 수동으로 mysql-0,1,2 실행시키고 group cluster 수동으로 만들고 join 시키기
kubectl apply -f ./k8_configs/mysql_depl_serv.yaml

# wait for mysql-0,1,2 to start
kubectl exec -it mysql-0 -n default -- mysqlsh root@localhost:3306
root
\sql
SET GLOBAL group_replication_bootstrap_group=ON;
START GROUP_REPLICATION;
SET GLOBAL group_replication_bootstrap_group=OFF;
-- 잘 됬는지 확인 (MEMBER_ROLE에 PRIMARY 있으면 된거)
SELECT * FROM performance_schema.replication_group_members;
\q

# mysql-1,2 각자 접속해서 cluster에 join 시키기 
kubectl exec -it mysql-1 -n default -- mysqlsh root@localhost:3306
root
\sql
RESET MASTER;   # local GTID 이력 삭제 
START GROUP_REPLICATION;
SELECT * FROM performance_schema.replication_group_members;
\q

kubectl exec -it mysql-2 -n default -- mysqlsh root@localhost:3306
root
\sql
RESET MASTER;   # local GTID 이력 삭제 
START GROUP_REPLICATION;
SELECT * FROM performance_schema.replication_group_members;
# 노드가 3개이고, 하나는 primary, 2개는 secondary임을 확인 
\q

+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+
| CHANNEL_NAME              | MEMBER_ID                            | MEMBER_HOST                                      | MEMBER_PORT | MEMBER_STATE | MEMBER_ROLE | MEMBER_VERSION | MEMBER_COMMUNICATION_STACK |
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+
| group_replication_applier | 271f6bbf-2e3a-11f0-9866-721273200872 | mysql-0.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | PRIMARY     | 8.0.37         | XCom                       |
| group_replication_applier | 2848ce32-2e3a-11f0-91a5-e6cd9afb9529 | mysql-1.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | SECONDARY   | 8.0.37         | XCom                       |
| group_replication_applier | 2998cdfe-2e3a-11f0-a159-a679022f8238 | mysql-2.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | SECONDARY   | 8.0.37         | XCom                       |
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+

B. failover 테스트
일부러 pod 하나 죽이기 죽이기 
kubectl delete pod mysql-0 -n default
kubectl exec -it mysql-1 -n default -- mysqlsh root@localhost:3306
\sql
SELECT * FROM performance_schema.replication_group_members;

+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+
| CHANNEL_NAME              | MEMBER_ID                            | MEMBER_HOST                                      | MEMBER_PORT | MEMBER_STATE | MEMBER_ROLE | MEMBER_VERSION | MEMBER_COMMUNICATION_STACK |
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+
| group_replication_applier | 271f6bbf-2e3a-11f0-9866-721273200872 | mysql-0.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | SECONDARY   | 8.0.37         | XCom                       |
| group_replication_applier | 2848ce32-2e3a-11f0-91a5-e6cd9afb9529 | mysql-1.mysql-headless.default.svc.cluster.local |        3306 | UNREACHABLE  | PRIMARY     | 8.0.37         | XCom                       |
| group_replication_applier | 2998cdfe-2e3a-11f0-a159-a679022f8238 | mysql-2.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | SECONDARY   | 8.0.37         | XCom                       |
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+

# 하나가 unreachable 상태임이 확인된다.
# 좀 기다리다가 primary가 완전히 맛이 갔다고 판단되는 경우, 재투표해서 1 primary, 1 secondary가 된다.


C. 자동 recovery 확인 
kubectl delete pod mysql-1 -n default
# 하나 죽이면 unreachable 상태가 된다
kubectl get pod
# restart 한 후에
kubectl exec -it mysql-0 -n default -- mysqlsh root@localhost:3306
\sql
SELECT * FROM performance_schema.replication_group_members;

# cluster에 pod 3개, 1 primary, 2 secondary인지 확인 
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+
| CHANNEL_NAME              | MEMBER_ID                            | MEMBER_HOST                                      | MEMBER_PORT | MEMBER_STATE | MEMBER_ROLE | MEMBER_VERSION | MEMBER_COMMUNICATION_STACK |
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+
| group_replication_applier | 271f6bbf-2e3a-11f0-9866-721273200872 | mysql-0.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | PRIMARY     | 8.0.37         | XCom                       |
| group_replication_applier | 2848ce32-2e3a-11f0-91a5-e6cd9afb9529 | mysql-1.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | SECONDARY   | 8.0.37         | XCom                       |
| group_replication_applier | 2998cdfe-2e3a-11f0-a159-a679022f8238 | mysql-2.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | SECONDARY   | 8.0.37         | XCom                       |
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+

# 1. UNREACHABLE -> ONLINE 복구되었고,
# 2. primary를 죽이니까, 재투표로 기존에 secondary가 primary가 되고 재시작한 원래 primary가 secondary가 된걸 확인 


# cluster가 잘 붙었는지 확인
kubectl exec -it mysql-1 -- mysql -u root -proot -e "SELECT * FROM performance_schema.replication_group_members;"
kubectl exec -it mysql-2 -- mysql -u root -proot -e "SELECT * FROM performance_schema.replication_group_members;" 
```

### c-3. mysql-router와 mysql-cluster 연결 확인 

```bash
#다음 mysql-router를 시작하여, 저 클러스터와 연결시킨다. 
kubectl apply -f ./k8_configs/mysql_router.yaml

# 먼저 수동으로 Group Replication 만든걸 InnoDB Cluster로 등록한다.
kubectl exec -it mysql-0 -n default -- mysqlsh root@localhost:3306
# 비밀번호 입력

JS > \js
// JavaScript 모드 예시
var cluster = dba.createCluster('EcommerceMysqlCluster', { adoptFromGR: true });

A new InnoDB Cluster will be created based on the existing replication group on instance 'mysql-0.mysql-headless.default.svc.cluster.local:3306'.

Creating InnoDB Cluster 'EcommerceMysqlCluster' on 'mysql-0.mysql-headless.default.svc.cluster.local:3306'...

Adding Seed Instance...
Adding Instance 'mysql-0.mysql-headless.default.svc.cluster.local:3306'...
Adding Instance 'mysql-1.mysql-headless.default.svc.cluster.local:3306'...
Adding Instance 'mysql-2.mysql-headless.default.svc.cluster.local:3306'...
Resetting distributed recovery credentials across the cluster...
Cluster successfully created based on existing replication group.

print(cluster.status());
```



```bash
# 먼저 mysql-router 재시작
kubectl rollout restart deployment mysql-router 

# mysql-router 상태확인
kubectl get pods | grep mysql-router


# 연결 테스트

# 읽기/쓰기 연결 테스트 (Router의 6446 포트)
# 이 명령은 mysql-router 파드 내부에서 실행하는 것입니다.
# Router의 6446 포트로 접속하면 현재 PRIMARY 노드(예: mysql-0)로 연결되어야 합니다.
kubectl exec -it mysql-router-76fdb7c799-6chlq -n default -- mysql -h 127.0.0.1 -P 6446 -u root -proot -e "SELECT @@hostname, @@port;"
+------------+--------+
| @@hostname | @@port |
+------------+--------+
| mysql-0    |   3306 |
+------------+--------+


# 읽기 전용 연결 테스트 (Router의 6447 포트)
# 이 명령도 mysql-router 파드 내부에서 실행하는 것입니다.
# Router의 6447 포트로 접속하면 현재 SECONDARY 노드들(예: mysql-1 또는 mysql-2) 중 하나로 연결되어야 합니다.
kubectl exec -it mysql-router-76fdb7c799-6chlq -n default -- mysql -h 127.0.0.1 -P 6447 -u root -proot -e "SELECT @@hostname, @@port;"
+------------+--------+
| @@hostname | @@port |
+------------+--------+
| mysql-1    |   3306 |
+------------+--------+
```



### c-4. 자동 fail over test 
```bash
kubectl get pod 


+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+
| CHANNEL_NAME              | MEMBER_ID                            | MEMBER_HOST                                      | MEMBER_PORT | MEMBER_STATE | MEMBER_ROLE | MEMBER_VERSION | MEMBER_COMMUNICATION_STACK |
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+
| group_replication_applier | 271f6bbf-2e3a-11f0-9866-721273200872 | mysql-0.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | SECONDARY   | 8.0.37         | XCom                       |
| group_replication_applier | 2848ce32-2e3a-11f0-91a5-e6cd9afb9529 | mysql-1.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | PRIMARY     | 8.0.37         | XCom                       |
| group_replication_applier | 2998cdfe-2e3a-11f0-a159-a679022f8238 | mysql-2.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | SECONDARY   | 8.0.37         | XCom                       |
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+

# 이게 맨 처음 상태.
# mysql-1이 primary, 나머지는 secondary


# PRIMARY 노드(mysql-0) 중지 (이 명령어는 주의해서 사용하세요!)
kubectl delete pod mysql-0 --grace-period=0 --force


kubectl get pod 
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+
| CHANNEL_NAME              | MEMBER_ID                            | MEMBER_HOST                                      | MEMBER_PORT | MEMBER_STATE | MEMBER_ROLE | MEMBER_VERSION | MEMBER_COMMUNICATION_STACK |
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+
| group_replication_applier | 271f6bbf-2e3a-11f0-9866-721273200872 | mysql-0.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | SECONDARY   | 8.0.37         | XCom                       |
| group_replication_applier | 2848ce32-2e3a-11f0-91a5-e6cd9afb9529 | mysql-1.mysql-headless.default.svc.cluster.local |        3306 | UNREACHABLE  | PRIMARY     | 8.0.37         | XCom                       |
| group_replication_applier | 2998cdfe-2e3a-11f0-a159-a679022f8238 | mysql-2.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | SECONDARY   | 8.0.37         | XCom                       |
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+

# mysql-1(primary)가 UNREACHABLE 상태로 되었다. 
# 좀 기다리다가 primary가 영영 죽은거 같으면, 재투표해서 나머지 SECONDARY 둘 중에 하나가 PRIMARY가 된다.


# 잠시 대기 후 연결 테스트
kubectl exec -it mysql-1 -- mysql -u root -proot -e "SELECT * FROM performance_schema.replication_group_members;"

+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+
| CHANNEL_NAME              | MEMBER_ID                            | MEMBER_HOST                                      | MEMBER_PORT | MEMBER_STATE | MEMBER_ROLE | MEMBER_VERSION | MEMBER_COMMUNICATION_STACK |
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+
| group_replication_applier | 271f6bbf-2e3a-11f0-9866-721273200872 | mysql-0.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | PRIMARY     | 8.0.37         | XCom                       |
| group_replication_applier | 2848ce32-2e3a-11f0-91a5-e6cd9afb9529 | mysql-1.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | SECONDARY   | 8.0.37         | XCom                       |
| group_replication_applier | 2998cdfe-2e3a-11f0-a159-a679022f8238 | mysql-2.mysql-headless.default.svc.cluster.local |        3306 | ONLINE       | SECONDARY   | 8.0.37         | XCom                       |
+---------------------------+--------------------------------------+--------------------------------------------------+-------------+--------------+-------------+----------------+----------------------------+

# 재투표 한 뒤, mysql-0이 primary가 되고, 기존에 primary인 mysql-1은 secondary가 되어 cluster에 재합류된걸 확인할 수 있다.
```
mysql-1이 새로운 primary로 설정된걸 확인할 수 있다.



### c-5. fastapi_module에서 mysql 연결할 때는?
```bash
# 읽기/쓰기 연결 (PRIMARY)
jdbc:mysql://mysql-router-access:6446/your_database

# 읽기 전용 연결 (SECONDARY)
jdbc:mysql://mysql-router-access:6447/your_database
```

이러면 read replica에서도 부하분산 해준다.




# D. step4. mysql InnoDB cluster & mysql-router w/ adminAPI 
- step3에서 수동으로 mysql-shell로 접속해서 cluster만들고 mysql pod를 join접속하고 mysql-router를 통해 primary / secondary 통신하는건 작동하긴 했는데, 문제는 자동 failover기능이 안되었다.
- router가 adminAPI를 통해 InnoDB cluster의 메타데이터를 읽고 라우팅하는게 원리라는데, mysql-shell로 접속해서 수동으로 클러스터에 join시킬 때 저 cluster 메타데이터에 데이터를 안쓴건지 여튼 어떤 모르는 이유 때문에 mysql-router를 통해 죽었다 재시작한 mysql-1을 접속하면, `ERROR: The instance 'mysql-1.mysql-headless:3306' does not belong to the cluster` 떴다. 
- 그래서 [mysql 공식문서](https://dev.mysql.com/doc/mysql-operator/en/)에서 k8s에서 innoDB cluster 및 mysql-router 배포하는거 대로 함
- step3에는 설정파일이 좀 복잡했다. mysql-0,1,2이 다 intialize -> ready 상태가 되었는지 체크한 후에, 상태가 어떠면 클러스터 만드는 커멘드 날리고 등등 좀 복잡했는데, step4대로 하면 설정파일이 깔끔하다. (물론 mysql-deploy-crds.yaml과 mysql-operator.yaml은 별개 github repo에 있던 파일을 로컬로 가져와서 그렇지... mycluster.yaml을 보면 매우 깔끔하다.)


#### B.1.5.8. innodb cluster (adminapi) & mysql router 
https://dev.mysql.com/doc/mysql-operator/en/ 
기반 

##### B.1.5.8.1. crds 
custom resource definition 다운로드 (for operator)
```bash 
kubectl apply -f k8_configs/mysql-deploy-crds.yaml

# 원본 삭제 
# kubectl delete -f https://raw.githubusercontent.com/mysql/mysql-operator/trunk/deploy/deploy-crds.yaml

# 원본 
# kubectl apply -f https://raw.githubusercontent.com/mysql/mysql-operator/trunk/deploy/deploy-crds.yaml
```

##### B.1.5.8.2. operator 
```bash
kubectl delete -f k8_configs/mysql-oprator.yaml

kubectl apply -f k8_configs/mysql-operator.yaml

# 원본 삭제 
# kubectl delete -f https://raw.githubusercontent.com/mysql/mysql-operator/trunk/deploy/deploy-operator.yaml --ignore-not-found=true

# 원본인데 sidecar에 권한에러나서 조금 수정함
#kubectl apply -f https://raw.githubusercontent.com/mysql/mysql-operator/trunk/deploy/deploy-operator.yaml

kubectl get pods -n mysql-operator

kubectl logs mysql-operator-7dd46bc99d-7fqvr -n mysql-operator
```

```bash
kubectl get deployment mysql-operator --namespace mysql-operator
```

##### B.1.5.8.3. 비밀번호 
```bash 
# 기존 mypwds Secret 삭제 (클러스터 삭제가 안 되더라도 일단 지우자)
kubectl delete secret mysql-root-password -n default

# 비밀번호 
echo -n 'root' | base64
cm9vdA==


kubectl create secret generic mysql-root-password -n default \
  --from-literal=rootPassword="cm9vdA==" 
  
# kubectl create secret generic mysql-root-password -n default --from-literal=password="cm9vdA=="


# 확인 
kubectl get secret mysql-root-password -n default -o yaml 

# mycluster.yaml 파일 수정: secretName: mypwds -> secretName: mysql-root-password 로 변경
```


##### B.1.5.8.4. cluster apply 
delete 
```bash
kubectl delete innodbcluster mycluster -n default 

# 클러스터 Pod들 강제 삭제 (Sts가 다시 살릴 수 있음) 
kubectl delete pod mycluster-0 mycluster-1 mycluster-2 -n default --force --grace-period=0 
# StatefulSet 강제 삭제 (이걸 지우면 Pod들 더이상 안 살아남)
# --cascade=orphan 옵션으로 PVC는 남겨둘 수 있음 
kubectl delete statefulset mycluster -n default --force --grace-period=0 --cascade=orphan 


kubectl get statefulset -n default -l mysql.oracle.com/cluster=mycluster
kubectl get service -n default -l mysql.oracle.com/cluster=mycluster
kubectl get pvc -n default -l mysql.oracle.com/cluster=mycluster 

kubectl delete statefulset <statefulset-이름> -n default --ignore-not-found=true kubectl delete service <service-이름> -n default --ignore-not-found=true # 
kubectl delete pvc <pvc-이름들> -n default 
```

apply 
```bash 
kubectl apply -f k8_configs/mycluster.yaml
```

```bash
# online 상태 될 때 까지 기다리기 
kubectl get innodbcluster --watch

kubectl get pods -n default -l mysql.oracle.com/cluster=mycluster -w 

kubectl get innodbcluster mycluster -n default -w 
```

```bash
kubectl run --rm -it myshell --image=container-registry.oracle.com/mysql/community-operator -- mysqlsh root@mycluster --sql

SQL> SELECT @@hostname 
```

###### B.1.5.8.4.1. 세부 설정 
https://dev.mysql.com/doc/mysql-operator/en/mysql-operator-innodbcluster-common.html 

##### B.1.5.8.5. connect to cluster 
```bash 
kubectl run --rm -it myshell --image=container-registry.oracle.com/mysql/community-operator -- mysqlsh 

\connect root@mycluster 

# root를 base64 인코딩한 값 
cm9vdA==

# AdminAPI 명령 실행 
\js 
cluster = dba.getCluster();
cluster.status();
```

##### B.1.5.8.6. connect to mysql-0,1,2 pod 개인 
이렇게 접속하거나, 
특정 mysql-0,1,2 접속하고 싶다면, 
```bash 
kubectl --namespace default exec -it mycluster-0 -- bash 

mysqlsh root@localhost 

# root를 base64 encoding 한 값 
cm9vdA==
```

##### B.1.5.8.7. 포트포워딩 
```bash 
kubectl port-forward service/mycluster 3306 

mysql -h127.0.0.1 -uroot -p 

mysql> select @@hostname; 
```

```bash
$> kubectl port-forward service/mycluster mysql 

Forwarding from 127.0.0.1:3306 -> 6446 
Forwarding from [::1]:3306 -> 6446 

^C 

$> kubectl port-forward service/mycluster mysql-ro 

Forwarding from 127.0.0.1:6447 -> 6447 
Forwarding from [::1]:6447 -> 6447
```

```
mysql: 3306 mysqlx: 33060 mysql-alternate: 6446 mysqlx-alternate: 6448 mysql-ro: 6447 mysqlx-ro: 6449 router-rest: 8443
```


##### B.1.5.8.8. router를 통한 r/w test 
쓰기 테스트 
```bash 
# myshell Pod는 종료됐을 테니 다시 run 명령으로 새 Pod 띄워서 테스트
kubectl run --rm -it myshell-router-test --image=container-registry.oracle.com/mysql/community-operator -- mysqlsh root@mycluster:6446 --sql 

# root를 base64 encoding 한 값 
cm9vdA==
```

```sql 
CREATE DATABASE test_db; 
USE test_db; 
CREATE TABLE test_table (id INT PRIMARY KEY);

INSERT INTO test_table (id) VALUES (1); 

SELECT * FROM test_table;

\q
```


읽기 테스트 
```bash 
kubectl run --rm -it myshell-router-test --image=container-registry.oracle.com/mysql/community-operator -- mysqlsh root@mycluster:6447 --sql 

# root를 base64 encoding 한 값 
cm9vdA==
```

```sql 
USE test_db; 
SELECT * FROM test_table;
```



##### B.1.5.8.9. mysql-router 
router를 통해서 cluster에 접속해야 한다 
(안그럼 brac 정책에 어긋남)
```bash 
kubectl get pod 
kubectl get deployment -n default 

kubectl logs mycluster-router-78d98d674-c5crx 
```

##### B.1.5.8.10. fastapi_module에서 mysqcluster과 통신 


##### B.1.5.8.11. backup 설정 
https://dev.mysql.com/doc/mysql-operator/en/mysql-operator-backups.html 

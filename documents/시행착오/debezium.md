# error handling 
## A.1. `show master status`가 작동 안됨!
이게 inno db cluster w/ mysql-router한테는 안먹히나 봄 

`ERROR MySQL|dbserver|streaming Producer failure io.debezium.DebeziumException: Unexpected error while connecting to MySQL and looking at GTID mode: ... Caused by: java.sql.SQLSyntaxErrorException: ... near 'MASTER STATUS' at line 1`

이건 `snapshot.mode: never` 로 스냅샷 단계를 건너뛰었는데도, **Binlog 스트리밍을 시작하려고 할 때 Debezium이 여전히 Binlog/GTID 위치를 파악하면서 `SHOW MASTER STATUS`라는 잘못된 쿼리를 날린다는 뜻이야** 


왜냐?

https://issues.redhat.com/browse/DBZ-7838 
에 따르면,
mysql이 버전업 하면서 
`show master status`같은 명령어들을 지워버렸기 때문!
다른 명령어로 대체함 

그래서 저 문서 읽어보면 debezium개발진이 패치에 반영했다고 함 

그래서 debezium 버전업을 2버전대에서 3버전대로 올리니까 해결됨 


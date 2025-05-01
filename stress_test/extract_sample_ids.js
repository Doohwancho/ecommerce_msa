// 실행법 
// step1: kubectl cp extract_sample_ids.js mongodb-stateful-0:/tmp/extract_sample_ids.js
// step2: kubectl exec -it mongodb-stateful-0 -- mongosh -u username -p password --authenticationDatabase admin --file /tmp/extract_sample_ids.js > product_ids.json
// step3: products.json 앞부분에 에러 메시지 지우기 


// extract_sample_ids.js
db = db.getSiblingDB('my_db');
const cursor = db.products.find({}, {_id: 1}).limit(10000);  // 10,000개 샘플 ID 추출
const ids = [];

while (cursor.hasNext()) {
  const doc = cursor.next();
  ids.push(doc._id.toString());
}

// 파일로 저장
print(JSON.stringify(ids));
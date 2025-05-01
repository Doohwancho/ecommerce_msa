import http from 'k6/http';
import { sleep } from 'k6';
import { SharedArray } from 'k6/data';
import { check, group } from 'k6';

// Q. how to run?
// docker run -i --network host --volume $(pwd):/app -w /app grafana/k6 run product_load_test_es.js

// product_ids.json 파일에서 ID 로드
const productIds = new SharedArray('product ids', function() {
  let fileContent = open('./elasticsearch_product_ids.json', 'text');
  let jsonMatch = fileContent.match(/\[.*\]/s);
  if (jsonMatch) {
    return JSON.parse(jsonMatch[0]);
  }
  return [];
});

export const options = {
  scenarios: {
    gradual_load_increase: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '1m', target: 100 },    // 1분 동안 1→100 VUs로 증가
        { duration: '2m', target: 100 },    // 2분 동안 100 VUs 유지
        { duration: '1m', target: 200 },    // 1분 동안 100→200 VUs로 증가
        { duration: '2m', target: 200 },    // 2분 동안 200 VUs 유지
        { duration: '1m', target: 300 },    // 1분 동안 200→300 VUs로 증가
        { duration: '2m', target: 300 },    // 2분 동안 300 VUs 유지
        // { duration: '1m', target: 400 },    // 1분 동안 300→400 VUs로 증가
        // { duration: '2m', target: 400 },    // 2분 동안 400 VUs 유지
        // { duration: '1m', target: 500 },    // 1분 동안 400→500 VUs로 증가
        // { duration: '3m', target: 500 },    // 3분 동안 500 VUs 유지
        { duration: '1m', target: 0 },      // 1분 동안 0 VUs로 감소
      ],
      gracefulRampDown: '30s',
    }
  },
  thresholds: {
    // 문턱값을 더 현실적으로 조정
    http_req_duration: ['p(95)<5000', 'p(99)<10000'],  // 95%의 요청이 5초 이내, 99%가 10초 이내
    http_req_failed: ['rate<0.05'],                    // 실패율 5% 미만
  },
};

export default function() {
  group('MongoDB Product Query', () => {
    // 지프 분포를 시뮬레이션하여 일부 핫 아이템에 더 많은 요청 집중
    const zipfIndex = Math.floor(Math.pow(Math.random(), 2) * productIds.length);
    const id = productIds[zipfIndex];
    
    const res = http.get(`http://host.docker.internal:8002/api/products/${id}`);
    
    check(res, {
      'status is 200': (r) => r.status === 200,
      'response time < 1s': (r) => r.timings.duration < 1000,
      'response time < 5s': (r) => r.timings.duration < 5000,
      'response time < 10s': (r) => r.timings.duration < 10000,
    });
    
    // 각 단계별 현재 VU 수를 로그로 출력
    // console.log(`Current VUs: ${__VU}, Current iterations: ${__ITER}, Response time: ${res.timings.duration}ms`);
    
    // 각 가상 사용자 간에 약간의 간격 추가 (실제 사용자 행동과 유사하게)
    sleep(Math.random() * 0.5 + 0.5);  // 0.5~1초 사이 무작위 대기
  });
}
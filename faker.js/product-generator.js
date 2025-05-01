// stream-product-generator.js
const fs = require('fs');
const { faker } = require('@faker-js/faker/locale/ko');

/*
sample product catalog data

curl -X POST http://localhost:8002/api/products/ \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Apple 2025 MacBook Pro",
    "description": "최신 Apple MacBook Pro, M3 Max 칩, 16인치 Liquid Retina XDR 디스플레이",
    "brand": "Apple",
    "model": "MUW73LL/A",
    "sku": "MBP-16-M3-MAX",
    "upc": "195949185694",
    "color": "Space Gray",
    "category_ids": [1, 2, 4],
    "category_path", "1/2/4",
    "category_level" 3,
    "primary_category_id": 4,
    "category_breadcrumbs": ["전자제품", "컴퓨터", "노트북"],
    "price": {
      "amount": 3499.99,
      "currency": "USD"
    },
    "stock": 100, 
    "weight": {
      "value": 4.8,
      "unit": "POUND"
    },
    "dimensions": {
      "length": 14.01,
      "width": 9.77,
      "height": 0.66,
      "unit": "INCH"
    },
    "attributes": {
      "processor": "M3 Max",
      "ram": "32GB",
      "storage": "1TB SSD",
      "screen_size": "16 inch",
      "resolution": "3456 x 2234"
    },
    "variants": [
      {
        "id": "variant1",
        "sku": "MBP-16-M3-MAX-SG-32GB-1TB",
        "color": "Space Gray",
        "storage": "1TB",
        "price": {
          "amount": 3499.99,
          "currency": "USD"
        },
        "attributes": {
          "processor": "M3 Max",
          "ram": "32GB"
        },
        "inventory": 50
      },
      {
        "id": "variant2",
        "sku": "MBP-16-M3-MAX-SIL-32GB-1TB",
        "color": "Silver",
        "storage": "1TB",
        "price": {
          "amount": 3499.99,
          "currency": "USD"
        },
        "attributes": {
          "processor": "M3 Max",
          "ram": "32GB"
        },
        "inventory": 35
      }
    ],
    "images": [
      {
        "url": "https://example.com/macbook-pro-1.jpg",
        "main": true
      },
      {
        "url": "https://example.com/macbook-pro-2.jpg",
        "main": false
      }
    ]
  }'
*/

// 카테고리 정의 및 기타 코드는 기존과 동일
const categories = [
  { id: 1, name: '전자제품', parent_id: null },
  { id: 2, name: '컴퓨터', parent_id: 1 },
  { id: 3, name: '스마트폰', parent_id: 1 },
  { id: 4, name: '노트북', parent_id: 2 },
  { id: 5, name: '데스크탑', parent_id: 2 },
  { id: 6, name: '태블릿', parent_id: 1 },
  { id: 7, name: '액세서리', parent_id: 1 },
  { id: 8, name: '가전제품', parent_id: null },
  { id: 9, name: '주방가전', parent_id: 8 },
  { id: 10, name: '생활가전', parent_id: 8 },
  { id: 11, name: '의류', parent_id: null },
  { id: 12, name: '남성의류', parent_id: 11 },
  { id: 13, name: '여성의류', parent_id: 11 },
  { id: 14, name: '아동의류', parent_id: 11 },
  // 수정된 부분: 신발과 가방은 의류의 하위 카테고리로, 가구는 인테리어의 하위 카테고리로 변경
  { id: 15, name: '신발', parent_id: 11 },
  { id: 16, name: '가방', parent_id: 11 },
  { id: 17, name: '도서', parent_id: null },
  { id: 18, name: '음반', parent_id: null },
  { id: 19, name: '가구', parent_id: 20 },
  { id: 20, name: '인테리어', parent_id: null }
];

// 브랜드 정의
const brands = {
  '전자제품': ['삼성전자', 'LG전자', 'Apple', 'Sony', 'Microsoft', 'Dell', 'HP', 'Lenovo', 'Asus', 'Acer'],
  '가전제품': ['삼성전자', 'LG전자', '위닉스', '다이슨', '쿠쿠', '테팔', '필립스', '일렉트로룩스', 'SK매직'],
  '의류': ['나이키', '아디다스', '자라', 'H&M', '유니클로', '무신사', '탑텐', '뉴발란스', '컨버스'],
  '신발': ['나이키', '아디다스', '푸마', '뉴발란스', '컨버스', '반스', '크록스', '닥터마틴'],
  '가방': ['샘소나이트', '루이비통', '구찌', '프라다', '코치', '마이클코어스', '케이트스페이드'],
  '도서': ['교보문고', '알라딘', 'YES24', '반디앤루니스'],
  '음반': ['SM', 'YG', 'JYP', 'HYBE', 'Universal Music', 'Sony Music'],
  '가구': ['이케아', '한샘', '일룸', '에이스침대', '시몬스', '까사미아', '리바트'],
  '인테리어': ['한샘', '일룸', '이케아', '리바트', '데코뷰', '오늘의집']
};

// 카테고리별 속성 정의 (생략)...
const categoryAttributes = {
  '노트북': {
    processor: ['Intel Core i3', 'Intel Core i5', 'Intel Core i7', 'Intel Core i9', 'AMD Ryzen 3', 'AMD Ryzen 5', 'AMD Ryzen 7', 'AMD Ryzen 9', 'Apple M1', 'Apple M2', 'Apple M3', 'Apple M3 Pro', 'Apple M3 Max'],
    ram: ['4GB', '8GB', '16GB', '32GB', '64GB'],
    storage: ['128GB SSD', '256GB SSD', '512GB SSD', '1TB SSD', '2TB SSD'],
    screen_size: ['13.3 inch', '14 inch', '15.6 inch', '16 inch', '17.3 inch'],
    resolution: ['1366 x 768', '1920 x 1080', '2560 x 1440', '3456 x 2234', '3840 x 2160']
  },
  '스마트폰': {
    processor: ['Snapdragon 8 Gen 3', 'Snapdragon 8 Gen 2', 'Exynos 2400', 'A17 Pro', 'A16 Bionic', 'Dimensity 9300'],
    ram: ['4GB', '6GB', '8GB', '12GB', '16GB'],
    storage: ['64GB', '128GB', '256GB', '512GB', '1TB'],
    screen_size: ['5.4 inch', '6.1 inch', '6.4 inch', '6.7 inch', '6.9 inch'],
    camera: ['12MP', '48MP', '50MP', '108MP', '200MP']
  },
  '태블릿': {
    processor: ['Apple A15', 'Apple A16', 'Apple M1', 'Apple M2', 'Snapdragon 8 Gen 2', 'Snapdragon 888', 'Dimensity 9000'],
    ram: ['3GB', '4GB', '6GB', '8GB', '16GB'],
    storage: ['32GB', '64GB', '128GB', '256GB', '512GB', '1TB'],
    screen_size: ['8 inch', '10.2 inch', '10.9 inch', '11 inch', '12.9 inch'],
    resolution: ['1620 x 2160', '2360 x 1640', '2732 x 2048', '2800 x 1752']
  },
  '데스크탑': {
    processor: ['Intel Core i3', 'Intel Core i5', 'Intel Core i7', 'Intel Core i9', 'AMD Ryzen 3', 'AMD Ryzen 5', 'AMD Ryzen 7', 'AMD Ryzen 9', 'AMD Threadripper'],
    ram: ['8GB', '16GB', '32GB', '64GB', '128GB'],
    storage: ['256GB SSD', '512GB SSD', '1TB SSD', '2TB SSD', '4TB SSD'],
    graphics: ['NVIDIA RTX 3050', 'NVIDIA RTX 3060', 'NVIDIA RTX 3070', 'NVIDIA RTX 3080', 'NVIDIA RTX 4060', 'NVIDIA RTX 4070', 'NVIDIA RTX 4080', 'NVIDIA RTX 4090', 'AMD RX 6600', 'AMD RX 6700', 'AMD RX 6800', 'AMD RX 6900', 'Intel Arc A750', 'Intel Arc A770']
  },
  '주방가전': {
    power: ['600W', '700W', '800W', '1000W', '1200W', '1500W'],
    capacity: ['1L', '1.5L', '1.8L', '2L', '3L', '4L', '5L', '6L'],
    color: ['화이트', '블랙', '실버', '레드', '블루', '핑크', '그린', '베이지']
  },
  '생활가전': {
    power: ['1000W', '1200W', '1400W', '1600W', '1800W', '2000W'],
    energy_efficiency: ['1등급', '2등급', '3등급', '4등급', '5등급'],
    noise_level: ['45dB', '50dB', '55dB', '60dB', '65dB']
  },
  '남성의류': {
    size: ['S', 'M', 'L', 'XL', 'XXL', '3XL'],
    material: ['면', '폴리에스테르', '울', '나일론', '데님', '캐시미어', '스웨이드'],
    pattern: ['솔리드', '스트라이프', '체크', '도트', '프린트', '기하학적'],
    fit: ['레귤러핏', '슬림핏', '오버핏', '스키니핏', '와이드핏']
  },
  '여성의류': {
    size: ['XS', 'S', 'M', 'L', 'XL', 'XXL'],
    material: ['면', '실크', '울', '폴리에스테르', '레이온', '린넨', '데님', '쉬폰'],
    pattern: ['솔리드', '플로럴', '스트라이프', '체크', '도트', '아니멀', '기하학적'],
    fit: ['레귤러핏', '슬림핏', '오버핏', '스키니핏', '와이드핏', 'A라인']
  },
  '아동의류': {
    age_group: ['신생아', '영아', '유아', '어린이', '주니어'],
    size: ['6M', '12M', '18M', '2Y', '3Y', '4Y', '5Y', '6Y', '7Y', '8Y', '10Y', '12Y'],
    material: ['면', '폴리에스테르', '플리스', '저지', '데님'],
    theme: ['캐릭터', '스포츠', '애니멀', '공주', '우주', '공룡', '무지']
  },
  '신발': {
    size: ['220', '230', '240', '250', '260', '270', '280', '290', '300'],
    material: ['가죽', '스웨이드', '캔버스', '메쉬', '고무', '합성피혁', '니트'],
    type: ['스니커즈', '로퍼', '부츠', '샌들', '힐', '플랫슈즈', '슬리퍼', '운동화']
  },
  '가방': {
    type: ['백팩', '숄더백', '크로스백', '토트백', '클러치', '지갑', '서류가방', '여행가방'],
    material: ['가죽', '캔버스', '나일론', '폴리에스테르', '코튼', '스웨이드'],
    size: ['소형', '중형', '대형', '특대형'],
    capacity: ['소품용', '일상용', '노트북 수납', '여행용']
  },
  '가구': {
    material: ['원목', '합판', 'MDF', '금속', '유리', '플라스틱', '대리석', '패브릭'],
    style: ['모던', '클래식', '미니멀', '북유럽', '빈티지', '인더스트리얼', '내추럴'],
    room: ['거실', '침실', '주방', '욕실', '사무실', '아이방', '다용도실']
  },
  '도서': {
    genre: ['소설', '시', '에세이', '자기계발', '경제/경영', '역사', '과학', '예술', '종교', '철학', '요리', '여행', '만화', '아동', '청소년'],
    format: ['하드커버', '페이퍼백', '전자책', '오디오북'],
    language: ['한국어', '영어', '일본어', '중국어', '프랑스어', '독일어', '스페인어']
  },
  '음반': {
    genre: ['팝', '록', 'R&B', '힙합', '재즈', '클래식', '컨트리', '일렉트로닉', 'K-POP', 'J-POP'],
    format: ['CD', 'LP', '디지털', '카세트'],
    release_type: ['정규앨범', '미니앨범', '싱글', '컴필레이션', '라이브', 'OST']
  },
  '인테리어': {
    type: ['조명', '벽지', '커튼', '러그', '쿠션', '화분', '액자', '캔들', '오브제'],
    style: ['모던', '클래식', '북유럽', '빈티지', '내추럴', '프로방스', '미니멀'],
    material: ['직물', '나무', '금속', '유리', '도자기', '플라스틱', '종이', '왁스']
  }
};

// 단위 정의
const units = {
  weight: ['GRAM', 'KILOGRAM', 'POUND', 'OUNCE'],
  dimension: ['CM', 'INCH', 'MM']
};

// 색상 정의
const colors = ['Black', 'White', 'Silver', 'Gray', 'Blue', 'Red', 'Green', 'Yellow', 'Purple', 'Pink', 'Brown', 'Navy', 'Orange', 'Gold', 'Space Gray', 'Midnight', 'Starlight'];

// 카테고리 경로 생성 함수 (breadcrumbs)
function getCategoryBreadcrumbs(categoryId) {
  const breadcrumbs = [];
  let currentCategory = categories.find(c => c.id === categoryId);
  
  while (currentCategory) {
    breadcrumbs.unshift(currentCategory.name);
    currentCategory = currentCategory.parent_id ? categories.find(c => c.id === currentCategory.parent_id) : null;
  }
  
  return breadcrumbs;
}

// 카테고리 ID 배열 생성 함수
function getCategoryIds(categoryId) {
  const ids = [categoryId];
  let currentCategory = categories.find(c => c.id === categoryId);
  
  while (currentCategory && currentCategory.parent_id) {
    ids.unshift(currentCategory.parent_id);
    currentCategory = categories.find(c => c.id === currentCategory.parent_id);
  }
  
  return ids;
}

// 카테고리 경로(path) 생성 함수 - 새로 추가
function getCategoryPath(categoryId) {
  const ids = getCategoryIds(categoryId);
  return ids.join('/');
}

// 카테고리 레벨 획득 함수 - 새로 추가
function getCategoryLevel(categoryId) {
  let level = 0;
  let currentCategory = categories.find(c => c.id === categoryId);
  
  while (currentCategory && currentCategory.parent_id) {
    level++;
    currentCategory = categories.find(c => c.id === currentCategory.parent_id);
  }
  
  return level;
}

// 카테고리 이름으로 브랜드 배열 가져오기 (기존 코드와 동일)
function getBrandsForCategory(categoryName) {
  // 먼저 카테고리 이름으로 직접 찾기
  if (brands[categoryName]) {
    return brands[categoryName];
  }
  
  // 상위 카테고리 찾기
  const category = categories.find(c => c.name === categoryName);
  if (category && category.parent_id) {
    const parentCategory = categories.find(c => c.id === category.parent_id);
    if (parentCategory && brands[parentCategory.name]) {
      return brands[parentCategory.name];
    }
  }
  
  // 기본값 반환
  return brands['전자제품'];
}

// 상품 속성 생성 함수 (기존 코드와 동일)
function generateAttributes(categoryName) {
  if (categoryAttributes[categoryName]) {
    const attrs = {};
    const categoryAttrs = categoryAttributes[categoryName];
    
    for (const [key, values] of Object.entries(categoryAttrs)) {
      attrs[key] = faker.helpers.arrayElement(values);
    }
    
    return attrs;
  }
  
  return {
    material: faker.helpers.arrayElement(['플라스틱', '금속', '나무', '직물', '가죽', '세라믹', '유리']),
    country_of_origin: faker.helpers.arrayElement(['한국', '중국', '베트남', '미국', '일본', '독일', '이탈리아', '프랑스'])
  };
}

// 상품 변형 생성 함수 (기존 코드와 동일)
function generateVariants(product, count = faker.number.int({ min: 1, max: 3 })) {
  const variants = [];
  
  for (let i = 0; i < count; i++) {
    const variantColor = faker.helpers.arrayElement(colors);
    let storage = '';
    
    if (product.category_breadcrumbs.includes('전자제품') || product.category_breadcrumbs.includes('컴퓨터')) {
      storage = product.attributes.storage || faker.helpers.arrayElement(['64GB', '128GB', '256GB', '512GB', '1TB']);
    }
    
    const variant = {
      id: `variant${i+1}`,
      sku: `${product.sku}-${variantColor.substring(0, 3).toUpperCase()}-${i+1}`,
      color: variantColor,
      price: {
        amount: product.price.amount * faker.number.float({ min: 0.9, max: 1.2, precision: 0.01 }),
        currency: product.price.currency
      },
      attributes: {},
      inventory: faker.number.int({ min: 0, max: 100 })
    };
    
    if (storage) {
      variant.storage = storage;
    }
    
    for (const [key, value] of Object.entries(product.attributes)) {
      if (faker.number.int({ min: 0, max: 1 }) === 1) {
        variant.attributes[key] = value;
      }
    }
    
    variants.push(variant);
  }
  
  return variants;
}

// 이미지 생성 함수 (기존 코드와 동일)
function generateImages(count = faker.number.int({ min: 1, max: 3 })) {
  const images = [];
  
  for (let i = 0; i < count; i++) {
    images.push({
      url: faker.image.url(),
      main: i === 0
    });
  }
  
  return images;
}

// 상품 데이터 생성 함수 - 업데이트됨
function generateProduct() {
  // 리프 카테고리만 선택하도록 수정 (하위 카테고리만 선택)
  const leafCategories = categories.filter(category => 
    !categories.some(c => c.parent_id === category.id)
  );
  
  const category = faker.helpers.arrayElement(leafCategories);
  const categoryBreadcrumbs = getCategoryBreadcrumbs(category.id);
  const categoryIds = getCategoryIds(category.id);
  const categoryPath = getCategoryPath(category.id);
  const categoryLevel = getCategoryLevel(category.id);
  
  const brand = faker.helpers.arrayElement(getBrandsForCategory(category.name));
  const modelNum = faker.string.alphanumeric(6).toUpperCase();
  const title = `${brand} ${faker.commerce.productName()} ${modelNum}`;
  
  const price = {
    amount: parseFloat(faker.commerce.price({ min: 10, max: 5000, dec: 2 })),
    currency: faker.helpers.arrayElement(['KRW', 'USD', 'EUR', 'JPY'])
  };
  
  if (price.currency === 'KRW') {
    price.amount = Math.round(price.amount * 1000); // 천원 단위로 반올림
  }
  
  const attributes = generateAttributes(category.name);
  const weightUnit = faker.helpers.arrayElement(units.weight);
  const dimensionUnit = faker.helpers.arrayElement(units.dimension);
  
  let weightRange = { min: 0.1, max: 5, precision: 0.1 };
  if (weightUnit === 'GRAM') {
    weightRange = { min: 100, max: 5000, precision: 1 };
  } else if (weightUnit === 'KILOGRAM') {
    weightRange = { min: 0.5, max: 20, precision: 0.1 };
  }
  
  const product = {
    title,
    description: faker.commerce.productDescription(),
    brand,
    model: modelNum,
    sku: `${brand.substring(0, 3).toUpperCase()}-${modelNum}-${faker.string.alphanumeric(3).toUpperCase()}`,
    upc: faker.string.numeric(12),
    color: faker.helpers.arrayElement(colors),
    
    // 카테고리 관련 필드 - 업데이트됨
    category_ids: categoryIds,
    primary_category_id: category.id,
    category_breadcrumbs: categoryBreadcrumbs,
    category_path: categoryPath,
    category_level: categoryLevel,
    
    price,
    stock: faker.number.int({ min: 0, max: 1000 }),
    stock_reserved: 0, // SAGA rollback을 위한 예약 재고량 추가
    weight: {
      value: faker.number.float(weightRange),
      unit: weightUnit
    },
    dimensions: {
      length: faker.number.float({ min: 1, max: 100, precision: 0.01 }),
      width: faker.number.float({ min: 1, max: 100, precision: 0.01 }),
      height: faker.number.float({ min: 0.1, max: 50, precision: 0.01 }),
      unit: dimensionUnit
    },
    attributes,
    variants: generateVariants({ 
      sku: `${brand.substring(0, 3).toUpperCase()}-${modelNum}-${faker.string.alphanumeric(3).toUpperCase()}`,
      price,
      attributes,
      category_breadcrumbs: categoryBreadcrumbs
    }),
    images: generateImages(),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  };
  
  return product;
}

// 메인 함수 - 스트림 방식으로 변경
async function main() {
  const productCount = 1000000; // 100만 개 상품
  const batchSize = 1000; // 한 번에 처리할 상품 수
  
  console.log(`Generating ${productCount} fake products using stream method...`);
  
  // 스트림 열기
  const writeStream = fs.createWriteStream('products.json');
  
  // 배열 시작 괄호 쓰기
  writeStream.write('[\n');
  
  // 배치 단위로 생성 및 저장
  for (let i = 0; i < productCount; i += batchSize) {
    const currentBatchSize = Math.min(batchSize, productCount - i);
    const batch = [];
    
    for (let j = 0; j < currentBatchSize; j++) {
      batch.push(generateProduct());
    }
    
    // 각 상품을 스트림에 쓰기
    for (let j = 0; j < batch.length; j++) {
      const isLast = (i + j === productCount - 1);
      writeStream.write(JSON.stringify(batch[j]) + (isLast ? '\n' : ',\n'));
    }
    
    // 메모리 관리를 위해 batch 비우기
    batch.length = 0;
    
    // 진행 상황 표시
    console.log(`Generated ${i + currentBatchSize} products...`);
  }
  
  // 배열 종료 괄호 쓰기
  writeStream.write(']');
  
  // 스트림 닫기
  writeStream.end();
  
  console.log(`Successfully generated ${productCount} products and saved to products.json`);
  console.log('\nTo import into MongoDB, use:');
  console.log('mongoimport --db mydb --collection products --file products.json --jsonArray');
}

// 스크립트 실행
main().catch(err => {
  console.error('Error:', err);
  process.exit(1);
});
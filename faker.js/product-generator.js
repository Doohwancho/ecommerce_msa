// const fs = require('fs');
// const { faker } = require('@faker-js/faker/locale/ko');

// // 카테고리 정의
// const categories = [
//   { id: 1, name: '전자제품', parent_id: null },
//   { id: 2, name: '컴퓨터', parent_id: 1 },
//   { id: 3, name: '스마트폰', parent_id: 1 },
//   { id: 4, name: '노트북', parent_id: 2 },
//   { id: 5, name: '데스크탑', parent_id: 2 },
//   { id: 6, name: '태블릿', parent_id: 1 },
//   { id: 7, name: '액세서리', parent_id: 1 },
//   { id: 8, name: '가전제품', parent_id: null },
//   { id: 9, name: '주방가전', parent_id: 8 },
//   { id: 10, name: '생활가전', parent_id: 8 },
//   { id: 11, name: '의류', parent_id: null },
//   { id: 12, name: '남성의류', parent_id: 11 },
//   { id: 13, name: '여성의류', parent_id: 11 },
//   { id: 14, name: '아동의류', parent_id: 11 },
//   { id: 15, name: '신발', parent_id: 11 },
//   { id: 16, name: '가방', parent_id: null },
//   { id: 17, name: '도서', parent_id: null },
//   { id: 18, name: '음반', parent_id: null },
//   { id: 19, name: '가구', parent_id: 20 },
//   { id: 20, name: '인테리어', parent_id: null }
// ];

// // 브랜드 정의
// const brands = {
//   '전자제품': ['삼성전자', 'LG전자', 'Apple', 'Sony', 'Microsoft', 'Dell', 'HP', 'Lenovo', 'Asus', 'Acer'],
//   '가전제품': ['삼성전자', 'LG전자', '위닉스', '다이슨', '쿠쿠', '테팔', '필립스', '일렉트로룩스', 'SK매직'],
//   '의류': ['나이키', '아디다스', '자라', 'H&M', '유니클로', '무신사', '탑텐', '뉴발란스', '컨버스'],
//   '신발': ['나이키', '아디다스', '푸마', '뉴발란스', '컨버스', '반스', '크록스', '닥터마틴'],
//   '가방': ['샘소나이트', '루이비통', '구찌', '프라다', '코치', '마이클코어스', '케이트스페이드'],
//   '도서': ['교보문고', '알라딘', 'YES24', '반디앤루니스'],
//   '음반': ['SM', 'YG', 'JYP', 'HYBE', 'Universal Music', 'Sony Music'],
//   '가구': ['이케아', '한샘', '일룸', '에이스침대', '시몬스', '까사미아', '리바트'],
//   '인테리어': ['한샘', '일룸', '이케아', '리바트', '데코뷰', '오늘의집']
// };

// // 카테고리별 속성 정의
// const categoryAttributes = {
//   '노트북': {
//     processor: ['Intel Core i3', 'Intel Core i5', 'Intel Core i7', 'Intel Core i9', 'AMD Ryzen 3', 'AMD Ryzen 5', 'AMD Ryzen 7', 'AMD Ryzen 9', 'Apple M1', 'Apple M2', 'Apple M3', 'Apple M3 Pro', 'Apple M3 Max'],
//     ram: ['4GB', '8GB', '16GB', '32GB', '64GB'],
//     storage: ['128GB SSD', '256GB SSD', '512GB SSD', '1TB SSD', '2TB SSD'],
//     screen_size: ['13.3 inch', '14 inch', '15.6 inch', '16 inch', '17.3 inch'],
//     resolution: ['1366 x 768', '1920 x 1080', '2560 x 1440', '3456 x 2234', '3840 x 2160']
//   },
//   '스마트폰': {
//     processor: ['Snapdragon 8 Gen 3', 'Snapdragon 8 Gen 2', 'Exynos 2400', 'A17 Pro', 'A16 Bionic', 'Dimensity 9300'],
//     ram: ['4GB', '6GB', '8GB', '12GB', '16GB'],
//     storage: ['64GB', '128GB', '256GB', '512GB', '1TB'],
//     screen_size: ['5.4 inch', '6.1 inch', '6.4 inch', '6.7 inch', '6.9 inch'],
//     camera: ['12MP', '48MP', '50MP', '108MP', '200MP']
//   },
//   '태블릿': {
//     processor: ['Apple A15', 'Apple A16', 'Apple M1', 'Apple M2', 'Snapdragon 8 Gen 2', 'Snapdragon 888', 'Dimensity 9000'],
//     ram: ['3GB', '4GB', '6GB', '8GB', '16GB'],
//     storage: ['32GB', '64GB', '128GB', '256GB', '512GB', '1TB'],
//     screen_size: ['8 inch', '10.2 inch', '10.9 inch', '11 inch', '12.9 inch'],
//     resolution: ['1620 x 2160', '2360 x 1640', '2732 x 2048', '2800 x 1752']
//   },
//   '데스크탑': {
//     processor: ['Intel Core i3', 'Intel Core i5', 'Intel Core i7', 'Intel Core i9', 'AMD Ryzen 3', 'AMD Ryzen 5', 'AMD Ryzen 7', 'AMD Ryzen 9', 'AMD Threadripper'],
//     ram: ['8GB', '16GB', '32GB', '64GB', '128GB'],
//     storage: ['256GB SSD', '512GB SSD', '1TB SSD', '2TB SSD', '4TB SSD'],
//     graphics: ['NVIDIA RTX 3050', 'NVIDIA RTX 3060', 'NVIDIA RTX 3070', 'NVIDIA RTX 3080', 'NVIDIA RTX 4060', 'NVIDIA RTX 4070', 'NVIDIA RTX 4080', 'NVIDIA RTX 4090', 'AMD RX 6600', 'AMD RX 6700', 'AMD RX 6800', 'AMD RX 6900', 'Intel Arc A750', 'Intel Arc A770']
//   },
//   '주방가전': {
//     power: ['600W', '700W', '800W', '1000W', '1200W', '1500W'],
//     capacity: ['1L', '1.5L', '1.8L', '2L', '3L', '4L', '5L', '6L'],
//     color: ['화이트', '블랙', '실버', '레드', '블루', '핑크', '그린', '베이지']
//   },
//   '생활가전': {
//     power: ['1000W', '1200W', '1400W', '1600W', '1800W', '2000W'],
//     energy_efficiency: ['1등급', '2등급', '3등급', '4등급', '5등급'],
//     noise_level: ['45dB', '50dB', '55dB', '60dB', '65dB']
//   }
// };

// // 단위 정의
// const units = {
//   weight: ['GRAM', 'KILOGRAM', 'POUND', 'OUNCE'],
//   dimension: ['CM', 'INCH', 'MM']
// };

// // 색상 정의
// const colors = ['Black', 'White', 'Silver', 'Gray', 'Blue', 'Red', 'Green', 'Yellow', 'Purple', 'Pink', 'Brown', 'Navy', 'Orange', 'Gold', 'Space Gray', 'Midnight', 'Starlight'];

// // 카테고리 경로 생성 함수
// function getCategoryBreadcrumbs(categoryId) {
//   const breadcrumbs = [];
//   let currentCategory = categories.find(c => c.id === categoryId);
  
//   while (currentCategory) {
//     breadcrumbs.unshift(currentCategory.name);
//     currentCategory = currentCategory.parent_id ? categories.find(c => c.id === currentCategory.parent_id) : null;
//   }
  
//   return breadcrumbs;
// }

// // 카테고리 ID 배열 생성 함수
// function getCategoryIds(categoryId) {
//   const ids = [categoryId];
//   let currentCategory = categories.find(c => c.id === categoryId);
  
//   while (currentCategory && currentCategory.parent_id) {
//     ids.push(currentCategory.parent_id);
//     currentCategory = categories.find(c => c.id === currentCategory.parent_id);
//   }
  
//   return ids.reverse();
// }

// // 카테고리 이름으로 브랜드 배열 가져오기
// function getBrandsForCategory(categoryName) {
//   // 먼저 카테고리 이름으로 직접 찾기
//   if (brands[categoryName]) {
//     return brands[categoryName];
//   }
  
//   // 상위 카테고리 찾기
//   const category = categories.find(c => c.name === categoryName);
//   if (category && category.parent_id) {
//     const parentCategory = categories.find(c => c.id === category.parent_id);
//     if (parentCategory && brands[parentCategory.name]) {
//       return brands[parentCategory.name];
//     }
//   }
  
//   // 기본값 반환
//   return brands['전자제품'];
// }

// // 상품 속성 생성 함수
// function generateAttributes(categoryName) {
//   // 카테고리별 속성 정의가 있는 경우
//   if (categoryAttributes[categoryName]) {
//     const attrs = {};
//     const categoryAttrs = categoryAttributes[categoryName];
    
//     // 각 속성에 대해 랜덤값 생성
//     for (const [key, values] of Object.entries(categoryAttrs)) {
//       attrs[key] = faker.helpers.arrayElement(values);
//     }
    
//     return attrs;
//   }
  
//   // 기본 속성 반환
//   return {
//     material: faker.helpers.arrayElement(['플라스틱', '금속', '나무', '직물', '가죽', '세라믹', '유리']),
//     country_of_origin: faker.helpers.arrayElement(['한국', '중국', '베트남', '미국', '일본', '독일', '이탈리아', '프랑스'])
//   };
// }

// // 상품 변형 생성 함수
// function generateVariants(product, count = faker.number.int({ min: 1, max: 5 })) {
//   const variants = [];
  
//   for (let i = 0; i < count; i++) {
//     const variantColor = faker.helpers.arrayElement(colors);
//     let storage = '';
    
//     // 전자제품인 경우 storage 속성 추가
//     if (product.category_breadcrumbs.includes('전자제품') || product.category_breadcrumbs.includes('컴퓨터')) {
//       storage = product.attributes.storage || faker.helpers.arrayElement(['64GB', '128GB', '256GB', '512GB', '1TB']);
//     }
    
//     const variant = {
//       id: `variant${i+1}`,
//       sku: `${product.sku}-${variantColor.substring(0, 3).toUpperCase()}-${i+1}`,
//       color: variantColor,
//       price: {
//         amount: product.price.amount * faker.number.float({ min: 0.9, max: 1.2, precision: 0.01 }),
//         currency: product.price.currency
//       },
//       attributes: {},
//       inventory: faker.number.int({ min: 0, max: 100 })
//     };
    
//     if (storage) {
//       variant.storage = storage;
//     }
    
//     // 상품 속성 중 일부를 변형에 복사
//     for (const [key, value] of Object.entries(product.attributes)) {
//       if (faker.number.int({ min: 0, max: 1 }) === 1) {
//         variant.attributes[key] = value;
//       }
//     }
    
//     variants.push(variant);
//   }
  
//   return variants;
// }

// // 이미지 생성 함수
// function generateImages(count = faker.number.int({ min: 1, max: 5 })) {
//   const images = [];
  
//   for (let i = 0; i < count; i++) {
//     images.push({
//       url: faker.image.url(),
//       main: i === 0 // 첫 번째 이미지를 메인으로 설정
//     });
//   }
  
//   return images;
// }

// // 상품 데이터 생성 함수
// function generateProduct() {
//   // 랜덤 카테고리 선택
//   const category = faker.helpers.arrayElement(categories);
//   const categoryBreadcrumbs = getCategoryBreadcrumbs(category.id);
//   const categoryIds = getCategoryIds(category.id);
  
//   // 브랜드 선택
//   const brand = faker.helpers.arrayElement(getBrandsForCategory(category.name));
  
//   // 모델명 생성
//   const modelNum = faker.string.alphanumeric(6).toUpperCase();
  
//   // 제품명 생성
//   const title = `${brand} ${faker.commerce.productName()} ${modelNum}`;
  
//   // 가격 생성
//   const price = {
//     amount: parseFloat(faker.commerce.price({ min: 10, max: 5000, dec: 2 })),
//     currency: faker.helpers.arrayElement(['KRW', 'USD', 'EUR', 'JPY'])
//   };
  
//   // 가격이 KRW인 경우 정수로 변환하고 1000 단위로 반올림
//   if (price.currency === 'KRW') {
//     price.amount = Math.round(price.amount * 1000) * 1000;
//   }
  
//   // 속성 생성
//   const attributes = generateAttributes(category.name);
  
//   // 무게 및 치수 단위 선택
//   const weightUnit = faker.helpers.arrayElement(units.weight);
//   const dimensionUnit = faker.helpers.arrayElement(units.dimension);
  
//   // 무게 값 범위 설정
//   let weightRange = { min: 0.1, max: 5, precision: 0.1 };
//   if (weightUnit === 'GRAM') {
//     weightRange = { min: 100, max: 5000, precision: 1 };
//   } else if (weightUnit === 'KILOGRAM') {
//     weightRange = { min: 0.5, max: 20, precision: 0.1 };
//   }
  
//   // 상품 객체 생성
//   const product = {
//     title,
//     description: faker.commerce.productDescription(),
//     brand,
//     model: modelNum,
//     sku: `${brand.substring(0, 3).toUpperCase()}-${modelNum}-${faker.string.alphanumeric(3).toUpperCase()}`,
//     upc: faker.string.numeric(12),
//     color: faker.helpers.arrayElement(colors),
//     category_ids: categoryIds,
//     primary_category_id: category.id,
//     category_breadcrumbs: categoryBreadcrumbs,
//     price,
//     stock: faker.number.int({ min: 0, max: 1000 }),
//     weight: {
//       value: faker.number.float(weightRange),
//       unit: weightUnit
//     },
//     dimensions: {
//       length: faker.number.float({ min: 1, max: 100, precision: 0.01 }),
//       width: faker.number.float({ min: 1, max: 100, precision: 0.01 }),
//       height: faker.number.float({ min: 0.1, max: 50, precision: 0.01 }),
//       unit: dimensionUnit
//     },
//     attributes,
//     variants: generateVariants({ 
//       sku: `${brand.substring(0, 3).toUpperCase()}-${modelNum}-${faker.string.alphanumeric(3).toUpperCase()}`,
//       price,
//       attributes,
//       category_breadcrumbs: categoryBreadcrumbs
//     }),
//     images: generateImages()
//   };
  
//   return product;
// }

// // 상품 데이터 생성 및 저장
// function generateProductCatalog(count) {
//   const products = [];
  
//   for (let i = 0; i < count; i++) {
//     const product = generateProduct();
//     products.push(product);
    
//     // 진행 상황 표시
//     if (i % 1000 === 0) {
//       console.log(`Generated ${i} products...`);
//     }
//   }
  
//   return products;
// }

// // 메인 함수
// function main() {
//   // 생성할 상품 수 설정
//   const productCount = 1000000;
  
//   console.log(`Generating ${productCount} fake products...`);
//   const products = generateProductCatalog(productCount);
  
//   // JSON 파일로 저장 - 배열 형식 [{}]
//   fs.writeFileSync('products.json', JSON.stringify(products, null, 2));
//   console.log(`Successfully generated ${productCount} products and saved to products.json`);
  
//   // MongoDB에 가져오기 명령어 안내
//   console.log('\nTo import into MongoDB, use:');
//   console.log('mongoimport --db mydb --collection products --file products.json --jsonArray');
// }

// // 스크립트 실행
// main();

// stream-product-generator.js
const fs = require('fs');
const { faker } = require('@faker-js/faker/locale/ko');

// 카테고리 정의 및 기타 코드는 기존과 동일 (생략)
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
  // 다른 카테고리 속성들... (생략)
};

// 단위 정의
const units = {
  weight: ['GRAM', 'KILOGRAM', 'POUND', 'OUNCE'],
  dimension: ['CM', 'INCH', 'MM']
};

// 색상 정의
const colors = ['Black', 'White', 'Silver', 'Gray', 'Blue', 'Red', 'Green', 'Yellow', 'Purple', 'Pink', 'Brown', 'Navy', 'Orange', 'Gold', 'Space Gray', 'Midnight', 'Starlight'];

// 카테고리 경로 생성 함수
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
    ids.push(currentCategory.parent_id);
    currentCategory = categories.find(c => c.id === currentCategory.parent_id);
  }
  
  return ids.reverse();
}

// 카테고리 이름으로 브랜드 배열 가져오기
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

// 다른 필요한 함수들... (생략)
// 상품 속성 생성 함수
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

// 상품 변형 생성 함수
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

// 이미지 생성 함수
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

// 상품 데이터 생성 함수
function generateProduct() {
  // 리프 카테고리만 선택하도록 수정 (하위 카테고리만 선택)
  const leafCategories = categories.filter(category => 
    !categories.some(c => c.parent_id === category.id)
  );
  
  const category = faker.helpers.arrayElement(leafCategories);
  const categoryBreadcrumbs = getCategoryBreadcrumbs(category.id);
  const categoryIds = getCategoryIds(category.id);
  
  const brand = faker.helpers.arrayElement(getBrandsForCategory(category.name));
  const modelNum = faker.string.alphanumeric(6).toUpperCase();
  const title = `${brand} ${faker.commerce.productName()} ${modelNum}`;
  
  const price = {
    amount: parseFloat(faker.commerce.price({ min: 10, max: 5000, dec: 2 })),
    currency: faker.helpers.arrayElement(['KRW', 'USD', 'EUR', 'JPY'])
  };
  
  if (price.currency === 'KRW') {
    price.amount = Math.round(price.amount * 1000) * 1000;
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
    category_ids: categoryIds,
    primary_category_id: category.id,
    category_breadcrumbs: categoryBreadcrumbs,
    price,
    stock: faker.number.int({ min: 0, max: 1000 }),
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
    images: generateImages()
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
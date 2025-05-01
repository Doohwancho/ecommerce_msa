const fs = require('fs');
const { faker } = require('@faker-js/faker/locale/ko');

/*
categories에 저장된 20개의 카테고리를 기반으로 계층화된 카테고리 데이터를 생성하고 .json 파일에 저장합니다.
*/

// 카테고리 정의
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
  { id: 15, name: '신발', parent_id: 11 },
  { id: 16, name: '가방', parent_id: 11 },
  { id: 17, name: '도서', parent_id: null },
  { id: 18, name: '음반', parent_id: null },
  { id: 19, name: '가구', parent_id: 20 },
  { id: 20, name: '인테리어', parent_id: null }
];

// 카테고리 경로 및 레벨 계산 함수
function getCategoryPath(categoryId) {
  const ids = [];
  let currentCategory = categories.find(c => c.id === categoryId);
  
  while (currentCategory) {
    ids.unshift(currentCategory.id);
    currentCategory = currentCategory.parent_id ? categories.find(c => c.id === currentCategory.parent_id) : null;
  }
  
  return ids.join('/');
}

function getCategoryLevel(categoryId) {
  let level = 0;
  let currentCategory = categories.find(c => c.id === categoryId);
  
  while (currentCategory && currentCategory.parent_id) {
    level++;
    currentCategory = categories.find(c => c.id === currentCategory.parent_id);
  }
  
  return level;
}

// 상위 및 하위 카테고리 연결 관계 계산
function calculateCategoryRelationships() {
  // 상위 카테고리 맵 만들기
  const childrenMap = {};
  
  // 모든 카테고리 ID에 대한 빈 하위 배열 초기화
  categories.forEach(category => {
    childrenMap[category.id] = [];
  });
  
  // 모든 카테고리를 순회하면서 상위-하위 관계 채우기
  categories.forEach(category => {
    if (category.parent_id) {
      childrenMap[category.parent_id].push(category.id);
    }
  });
  
  return childrenMap;
}

// 카테고리 메타데이터 생성
function generateCategoryMetadata(category) {
  const created = faker.date.past();
  const updated = faker.date.between({ from: created, to: new Date() });
  
  return {
    created_at: created.toISOString(),
    updated_at: updated.toISOString(),
    is_active: faker.datatype.boolean({ probability: 0.9 }), // 90%는 활성화
    display_order: faker.number.int({ min: 1, max: 100 }),
    icon_url: faker.image.url() + `?category=${category.id}`,
    is_featured: faker.datatype.boolean({ probability: 0.3 }) // 30%는 주목 카테고리
  };
}

// 카테고리 설명 및 SEO 정보 생성
function generateCategoryDescription(category) {
  return {
    short_description: faker.lorem.sentence(),
    long_description: faker.lorem.paragraph(3),
    seo: {
      meta_title: `${category.name} | 쇼핑몰`,
      meta_description: faker.lorem.sentences(2),
      meta_keywords: faker.lorem.words(5),
      slug: category.name.toLowerCase().replace(/\s+/g, '-')
    }
  };
}

// 카테고리 문서 생성 함수
function generateCategoryDocument(category, childrenMap) {
  const path = getCategoryPath(category.id);
  const level = getCategoryLevel(category.id);
  const children = childrenMap[category.id];
  
  // 기본 카테고리 정보
  const categoryDoc = {
    _id: category.id,
    name: category.name,
    parent_id: category.parent_id,
    path: path,
    level: level,
    children: children,
    ...generateCategoryMetadata(category),
    ...generateCategoryDescription(category)
  };
  
  // 이미지 URL 추가 (카테고리 유형에 따라 다양한 이미지)
  categoryDoc.image_urls = Array.from({ length: faker.number.int({ min: 1, max: 3 }) }, (_, i) => ({
    url: faker.image.url() + `?category=${category.id}&image=${i}`,
    alt: `${category.name} 이미지 ${i+1}`,
    is_primary: i === 0
  }));
  
  // 필터 옵션 (카테고리에 따른 상이한 필터)
  categoryDoc.filter_options = [];
  
  // 브랜드 필터 (대부분의 카테고리에 적용)
  categoryDoc.filter_options.push({
    name: "브랜드",
    type: "multi_select",
    values: Array.from({ length: faker.number.int({ min: 5, max: 15 }) }, () => 
      faker.company.name()
    )
  });
  
  // 가격 필터 (모든 카테고리에 적용)
  categoryDoc.filter_options.push({
    name: "가격",
    type: "range",
    min: 0,
    max: 1000000,
    unit: "원"
  });
  
  // 전자제품 계열 필터
  if (path.startsWith('1/')) {
    categoryDoc.filter_options.push({
      name: "메모리",
      type: "multi_select",
      values: ["4GB", "8GB", "16GB", "32GB", "64GB"]
    });
    categoryDoc.filter_options.push({
      name: "저장공간",
      type: "multi_select",
      values: ["128GB", "256GB", "512GB", "1TB", "2TB"]
    });
  }
  
  // 의류 계열 필터
  if (path.startsWith('11/')) {
    categoryDoc.filter_options.push({
      name: "사이즈",
      type: "multi_select",
      values: ["XS", "S", "M", "L", "XL", "XXL"]
    });
    categoryDoc.filter_options.push({
      name: "색상",
      type: "color",
      values: ["빨강", "파랑", "검정", "흰색", "회색", "베이지"]
    });
  }
  
  return categoryDoc;
}

// 메인 함수
async function main() {
  // 카테고리 관계 계산
  const childrenMap = calculateCategoryRelationships();
  
  // 모든 카테고리 문서 생성
  const categoryDocuments = categories.map(category => 
    generateCategoryDocument(category, childrenMap)
  );
  
  // 파일에 저장
  fs.writeFileSync(
    'categories.json',
    JSON.stringify(categoryDocuments, null, 2)
  );
  
  console.log(`카테고리 데이터 ${categoryDocuments.length}개가 성공적으로 생성되어 categories.json 파일에 저장되었습니다.`);
  
  // JSON 배열 형식으로도 저장 (몽고DB 임포트용)
  fs.writeFileSync(
    'categories_array.json',
    JSON.stringify(categoryDocuments)
  );
  
  console.log('MongoDB 임포트를 위한 categories_array.json 파일도 생성되었습니다.');
  console.log('MongoDB 임포트 명령어:');
  console.log('mongoimport --db mydb --collection categories --file categories_array.json --jsonArray');
}

// 스크립트 실행
main().catch(err => {
  console.error('에러:', err);
  process.exit(1);
});
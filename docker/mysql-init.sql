-- 테스트 전용 DB. 테스트가 실제 데이터(nutrition DB)를 건드리지 않게 분리한다.
-- MYSQL_USER로 만든 사용자 이름이 'nutri'라고 가정한다 (.env.example과 같게 유지).
CREATE DATABASE IF NOT EXISTS nutrition_test CHARACTER SET utf8mb4;
GRANT ALL PRIVILEGES ON nutrition_test.* TO 'nutri'@'%';

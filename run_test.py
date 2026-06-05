import json
import requests
import time

DATA_FILE = "data/Logic_Based_Educational_Queries.json"
API_URL = "http://127.0.0.1:8000/predict"
LIMIT = 5  # Số lượng cụm câu hỏi muốn test (Đổi thành None nếu muốn test toàn bộ file)

def run_tests():
    print(f"Đang đọc dữ liệu từ {DATA_FILE}...")
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    if LIMIT:
        print(f"Chỉ chạy test {LIMIT} mục đầu tiên (Do file rất lớn, có thể tốn nhiều chi phí API)")
        data = data[:LIMIT]
        
    passed = 0
    failed = 0
    total_questions = 0
    
    for i, item in enumerate(data):
        # Lấy dữ kiện bằng ngôn ngữ tự nhiên
        premises = item.get("premises-NL", [])
        questions = item.get("questions", [])
        answers = item.get("answers", [])
        
        # Mỗi item có thể có nhiều câu hỏi và đáp án tương ứng
        for q_idx, (question, expected) in enumerate(zip(questions, answers)):
            total_questions += 1
            payload = {
                "question": question,
                "premises": premises
            }
            
            print(f"⏳ Đang test Mục {i+1}, Câu hỏi {q_idx+1}...")
            try:
                response = requests.post(API_URL, json=payload)
                if response.status_code != 200:
                    failed += 1
                    print(f"⚠️ [ERROR] API trả về lỗi {response.status_code}: {response.text}")
                    print("-" * 50)
                    continue
                    
                response_data = response.json()
                # Lấy kết quả trả về từ API
                actual = response_data.get("answer", "")
                
                # So sánh đáp án (Chuyển về chữ thường và xóa khoảng trắng thừa để so sánh chính xác hơn)
                if str(actual).strip().lower() == str(expected).strip().lower():
                    passed += 1
                    print(f"✅ [PASS]")
                else:
                    failed += 1
                    print(f"❌ [FAIL]")
                    print(f"   🔸 Cần ra: {expected}")
                    print(f"   🔻 Thực ra: {actual}")
                    
            except Exception as e:
                failed += 1
                print(f"⚠️ [ERROR] Lỗi không gọi được API: {e}")
                
            print("-" * 50)
            
            # Tạm nghỉ 1 giây giữa các request để tránh bị OpenRouter/LLM API chặn vì gửi quá nhanh
            time.sleep(1) 

    print("=" * 50)
    print(f"🎯 TỔNG KẾT: ✅ Pass: {passed} | ❌ Fail: {failed} | 🔢 Tổng số câu: {total_questions}")

if __name__ == "__main__":
    run_tests()

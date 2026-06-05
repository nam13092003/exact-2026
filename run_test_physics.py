import json
import requests
import time

DATA_FILE = "data/Physics_Problems_100_generated_checked.json"
API_URL = "http://127.0.0.1:8000/predict"
LIMIT = 5  # Số lượng câu hỏi muốn test (Đổi thành None nếu muốn test toàn bộ file)

def run_tests():
    print(f"Đang đọc dữ liệu từ {DATA_FILE}...")
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    if LIMIT:
        print(f"Chỉ chạy test {LIMIT} câu đầu tiên (Do file có thể lớn, tốn chi phí API)")
        data = data[:LIMIT]
        
    passed = 0
    failed = 0
    total_questions = len(data)
    
    for i, item in enumerate(data):
        # Lấy dữ kiện từ file Physics
        question_id = item.get("id", f"Q{i+1}")
        question = item.get("question", "")
        expected_answer = item.get("answer", "")
        expected_unit = item.get("unit", "")
        
        # Payload không có premises (vì bài lý không có, chỉ có câu hỏi)
        payload = {
            "question": question
        }
        
        print(f"⏳ Đang test Câu {question_id}...")
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
            
            # So sánh đáp án (Chuyển về chữ thường và xóa khoảng trắng thừa)
            if str(actual).strip().lower() == str(expected_answer).strip().lower():
                passed += 1
                print(f"✅ [PASS]")
            else:
                failed += 1
                print(f"❌ [FAIL]")
                print(f"   🔸 Cần ra: {expected_answer} {expected_unit}")
                print(f"   🔻 Thực ra: {actual}")
                print(f"   Question: {question}")
                
        except Exception as e:
            failed += 1
            print(f"⚠️ [ERROR] Lỗi không gọi được API: {e}")
            
        print("-" * 50)
        
        # Tạm nghỉ 1 giây giữa các request để tránh bị API chặn vì gửi quá nhanh
        time.sleep(1) 

    print("=" * 50)
    print(f"🎯 TỔNG KẾT: ✅ Pass: {passed} | ❌ Fail: {failed} | 🔢 Tổng số câu: {total_questions}")

if __name__ == "__main__":
    run_tests()

import json
import requests
import time

API_URL = "http://127.0.0.1:8000/predict"

# Tùy chỉnh số lượng test cho từng phần (None = test tất cả)
LIMIT_LOGIC = 5     # Đang set 5 cụm (khoảng 10 câu) cho Logic
LIMIT_PHYSICS = 100 # Đang set 100 câu cho Physics

def run_logic_tests():
    data_file = "data/Logic_Based_Educational_Queries.json"
    print(f"\n{'='*50}\n🚀 BẮT ĐẦU TEST LOGIC ({data_file})\n{'='*50}")
    
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    if LIMIT_LOGIC:
        data = data[:LIMIT_LOGIC]
        
    passed, failed, total = 0, 0, 0
    
    for i, item in enumerate(data):
        premises = item.get("premises-NL", [])
        questions = item.get("questions", [])
        answers = item.get("answers", [])
        
        for q_idx, (question, expected) in enumerate(zip(questions, answers)):
            total += 1
            payload = {"question": question, "premises": premises}
            
            print(f"⏳ [Logic] Đang test Mục {i+1}, Câu hỏi {q_idx+1}...")
            try:
                response = requests.post(API_URL, json=payload)
                if response.status_code == 200:
                    actual = response.json().get("answer", "")
                    if str(actual).strip().lower() == str(expected).strip().lower():
                        passed += 1
                        print("   ✅ PASS")
                    else:
                        failed += 1
                        print(f"   ❌ FAIL | Cần ra: {expected} | Thực ra: {actual}")
                else:
                    failed += 1
                    print(f"   ⚠️ ERROR | Code {response.status_code}")
            except Exception as e:
                failed += 1
                print(f"   ⚠️ ERROR | Lỗi gọi API: {e}")
                
            time.sleep(1)
            
    print(f"\n🎯 TỔNG KẾT LOGIC: ✅ Pass {passed} | ❌ Fail {failed} | Tổng {total}")
    return passed, failed, total


def run_physics_tests():
    data_file = "data/Physics_Problems_100_generated_checked.json"
    print(f"\n{'='*50}\n🚀 BẮT ĐẦU TEST PHYSICS ({data_file})\n{'='*50}")
    
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    if LIMIT_PHYSICS:
        data = data[:LIMIT_PHYSICS]
        
    passed, failed, total = 0, 0, 0
    
    for i, item in enumerate(data):
        question_id = item.get("id", f"Q{i+1}")
        question = item.get("question", "")
        expected = item.get("answer", "")
        expected_unit = item.get("unit", "")
        
        payload = {"question": question}
        total += 1
        
        print(f"⏳ [Physics] Đang test Câu {question_id}...")
        try:
            response = requests.post(API_URL, json=payload)
            if response.status_code == 200:
                actual = response.json().get("answer", "")
                if str(actual).strip().lower() == str(expected).strip().lower():
                    passed += 1
                    print("   ✅ PASS")
                else:
                    failed += 1
                    print(f"   ❌ FAIL | Cần ra: {expected} {expected_unit} | Thực ra: {actual}")
            else:
                failed += 1
                print(f"   ⚠️ ERROR | Code {response.status_code}")
        except Exception as e:
            failed += 1
            print(f"   ⚠️ ERROR | Lỗi gọi API: {e}")
            
        time.sleep(1)
        
    print(f"\n🎯 TỔNG KẾT PHYSICS: ✅ Pass {passed} | ❌ Fail {failed} | Tổng {total}")
    return passed, failed, total


if __name__ == "__main__":
    t_start = time.time()
    
    l_pass, l_fail, l_total = run_logic_tests()
    p_pass, p_fail, p_total = run_physics_tests()
    
    t_end = time.time()
    
    print(f"\n{'*'*50}")
    print(f"🏆 KẾT QUẢ TOÀN BỘ (Thời gian chạy: {int(t_end - t_start)}s)")
    print(f"{'*'*50}")
    print(f"🔹 LOGIC:   ✅ {l_pass} | ❌ {l_fail} | Tổng: {l_total}")
    print(f"🔹 PHYSICS: ✅ {p_pass} | ❌ {p_fail} | Tổng: {p_total}")
    print(f"🔹 TỔNG:    ✅ {l_pass+p_pass} | ❌ {l_fail+p_fail} | TỔNG CỘNG: {l_total+p_total}")
    print(f"{'*'*50}")

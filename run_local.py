import json
import time
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Cấu hình logging để vừa in ra màn hình, vừa lưu vào file "test_results.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.FileHandler("test_results.log", mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Import trực tiếp logic xử lý thay vì gọi qua API
from agents.llm import OpenRouterClient
from agents.workflows import ExactGraph

# Tùy chỉnh số lượng test (None = test tất cả)
LIMIT_LOGIC = 5     
LIMIT_PHYSICS = 100 

import re
import math
from agents.physics.Parsing.Parsing_Agent import UNIT_TO_SI, _canonical_unit_key

def compare_physics_answer(actual: str, expected_val: str, expected_unit: str) -> bool:
    expected_full = f"{expected_val} {expected_unit}".strip().lower()
    actual_str = str(actual).strip().lower()
    
    # 1. Khớp hoàn toàn chuỗi
    if actual_str == expected_full or actual_str == str(expected_val).strip().lower():
        return True
        
    # 2. Quy đổi đơn vị để so sánh
    actual_match = re.search(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*)$", actual_str)
    if not actual_match:
        return False
        
    try:
        act_val = float(actual_match.group(1))
        act_unit = actual_match.group(2).strip()
        exp_val = float(expected_val)
        exp_unit = str(expected_unit).strip()
        
        act_si_scale, act_si_unit = UNIT_TO_SI.get(_canonical_unit_key(act_unit), (1.0, act_unit.lower()))
        exp_si_scale, exp_si_unit = UNIT_TO_SI.get(_canonical_unit_key(exp_unit), (1.0, exp_unit.lower()))
        
        # Nếu cùng thứ nguyên SI (VD: J)
        if act_si_unit == exp_si_unit:
            act_si_val = act_val * act_si_scale
            exp_si_val = exp_val * exp_si_scale
            # Cho phép sai số 0.1% (rel_tol=1e-3)
            return math.isclose(act_si_val, exp_si_val, rel_tol=1e-3, abs_tol=1e-9)
    except Exception:
        pass
        
    return False

# Bật/tắt chạy test cho từng phần
RUN_LOGIC = False    # Tắt test Logic
RUN_PHYSICS = True   # Chỉ bật test Physics

def setup_graph(force_route=None):
    logging.info(f"⏳ Đang khởi tạo AI (Bỏ qua Classifier, Route ép buộc: {force_route})...")
    ROOT = Path(__file__).resolve().parent
    physics_kb = ROOT / "data" / "Physics_Problems_Text_Only_removeQA.json"
    
    # Khởi tạo LLM
    llm = OpenRouterClient(api_key_env="OR_TOKEN")
    
    # Tạo một Classifier giả (Dummy) để ép AI nhảy thẳng vào đồ thị Physics hoặc Logic
    # Việc này giúp né lỗi "idf vector is not fitted" của bộ Classifier cũ.
    class DummyClassifier:
        def run(self, question):
            return {"question": question, "Type": force_route}
            
    classifier = DummyClassifier() if force_route else None
    
    graph = ExactGraph(llm=llm, physics_kb_path=str(physics_kb), classifier=classifier)
    return graph

def run_logic_tests(graph: ExactGraph):
    data_file = "data/Logic_Based_Educational_Queries.json"
    logging.info(f"\n{'='*50}\n🚀 BẮT ĐẦU TEST LOGIC ({data_file})\n{'='*50}")
    
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
            
            logging.info(f"⏳ [Logic] Đang test Mục {i+1}, Câu hỏi {q_idx+1}...")
            try:
                # Gọi trực tiếp hàm xử lý, không qua HTTP/requests
                response = graph.predict(payload)
                actual = response.get("answer", "")
                
                if str(actual).strip().lower() == str(expected).strip().lower():
                    passed += 1
                    logging.info("   ✅ PASS")
                else:
                    failed += 1
                    logging.info(f"   ❌ FAIL | Cần ra: {expected} | Thực ra: {actual}")
                    logging.info(f"   📝 Đề bài: {question}")
                    explanation = response.get("explanation", "")
                    if explanation:
                        logging.info(f"   💡 Lời giải của AI:\n      {explanation}\n")
            except Exception as e:
                failed += 1
                logging.info(f"   ⚠️ ERROR | Lỗi hệ thống: {e}")
                
            time.sleep(1) # Tránh gọi LLM quá dồn dập
            
    logging.info(f"\n🎯 TỔNG KẾT LOGIC: ✅ Pass {passed} | ❌ Fail {failed} | Tổng {total}")
    return passed, failed, total

def run_physics_tests(graph: ExactGraph):
    data_file = "data/Physics_Problems_100_generated_checked.json"
    logging.info(f"\n{'='*50}\n🚀 BẮT ĐẦU TEST PHYSICS ({data_file})\n{'='*50}")
    
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
        
        logging.info(f"⏳ [Physics] Đang test Câu {question_id}...")
        try:
            # Gọi trực tiếp hàm xử lý
            response = graph.predict(payload)
            actual = str(response.get("answer", ""))
            
            if compare_physics_answer(actual, expected, expected_unit):
                passed += 1
                logging.info("   ✅ PASS")
            else:
                failed += 1
                logging.info(f"   ❌ FAIL | Cần ra: {expected_full} | Thực ra: {actual}")
                logging.info(f"   📝 Đề bài: {question}")
                explanation = response.get("explanation", "")
                if explanation:
                    logging.info(f"   💡 Lời giải của AI:\n      {explanation}\n")
        except Exception as e:
            failed += 1
            logging.info(f"   ⚠️ ERROR | Lỗi hệ thống: {e}")
            
        time.sleep(1)
        
    logging.info(f"\n🎯 TỔNG KẾT PHYSICS: ✅ Pass {passed} | ❌ Fail {failed} | Tổng {total}")
    return passed, failed, total


if __name__ == "__main__":
    t_start = time.time()
    
    l_pass, l_fail, l_total = 0, 0, 0
    p_pass, p_fail, p_total = 0, 0, 0
    
    if RUN_LOGIC:
        graph_logic = setup_graph(force_route="logic")
        l_pass, l_fail, l_total = run_logic_tests(graph_logic)
        
    if RUN_PHYSICS:
        graph_physics = setup_graph(force_route="physics")
        p_pass, p_fail, p_total = run_physics_tests(graph_physics)
    
    t_end = time.time()
    
    logging.info(f"\n{'*'*50}")
    logging.info(f"🏆 KẾT QUẢ TOÀN BỘ (Thời gian chạy: {int(t_end - t_start)}s)")
    logging.info(f"{'*'*50}")
    if RUN_LOGIC:
        logging.info(f"🔹 LOGIC:   ✅ {l_pass} | ❌ {l_fail} | Tổng: {l_total}")
    if RUN_PHYSICS:
        logging.info(f"🔹 PHYSICS: ✅ {p_pass} | ❌ {p_fail} | Tổng: {p_total}")
    logging.info(f"🔹 TỔNG:    ✅ {l_pass+p_pass} | ❌ {l_fail+p_fail} | TỔNG CỘNG: {l_total+p_total}")
    logging.info(f"{'*'*50}")

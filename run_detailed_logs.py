import json
import time
import run_local

# 1. Patch agents.llm.llm_provider.LLMClientBase
try:
    from agents.llm.llm_provider import LLMClientBase
    original_chat_base = LLMClientBase.chat
    
    def patched_chat_base(self, messages, temperature=0.0, max_tokens=1024, response_format=None, stage="llm.chat"):
        response_text = original_chat_base(self, messages, temperature, max_tokens, response_format, stage)
        with open("detailed_llm_logs.txt", "a", encoding="utf-8") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"=== STAGE: {stage} ===\n")
            f.write("--- PROMPT MESSAGES ---\n")
            f.write(json.dumps(messages, indent=2, ensure_ascii=False))
            f.write("\n\n--- LLM RAW RESPONSE (JSON) ---\n")
            f.write(response_text)
            f.write(f"\n{'='*80}\n")
        return response_text
    
    LLMClientBase.chat = patched_chat_base
except Exception as e:
    print("Warning: LLMClientBase not patched", e)

# 2. Patch agents.llm_client.VLLMClient (Dùng cho pipeline cũ)
try:
    from agents.llm_client import VLLMClient
    original_chat_vllm = VLLMClient.chat
    
    def patched_chat_vllm(self, messages, temperature=0.0, max_tokens=1024, response_format=None):
        response_text = original_chat_vllm(self, messages, temperature, max_tokens, response_format)
        with open("detailed_llm_logs.txt", "a", encoding="utf-8") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"=== VLLMClient ===\n")
            f.write("--- PROMPT MESSAGES ---\n")
            f.write(json.dumps(messages, indent=2, ensure_ascii=False))
            f.write("\n\n--- LLM RAW RESPONSE (JSON) ---\n")
            f.write(response_text)
            f.write(f"\n{'='*80}\n")
        return response_text
        
    VLLMClient.chat = patched_chat_vllm
except Exception as e:
    print("Warning: VLLMClient not patched", e)

if __name__ == "__main__":
    print("Bat dau chay test voi Detailed Logging...")
    print("Logs se duoc luu tai: detailed_llm_logs.txt")
    
    with open("detailed_llm_logs.txt", "w", encoding="utf-8") as f:
        f.write("DETAILED LLM LOGS\n")
        
    # Bạn có thể chỉnh sửa số lượng test chạy ở đây
    run_local.RUN_LOGIC = True
    run_local.RUN_PHYSICS = True
    run_local.LIMIT_LOGIC = 1
    run_local.LIMIT_PHYSICS = 1
    
    t_start = time.time()
    
    if run_local.RUN_LOGIC:
        graph_logic = run_local.setup_graph(force_route="logic")
        run_local.run_logic_tests(graph_logic)
        
    if run_local.RUN_PHYSICS:
        graph_physics = run_local.setup_graph(force_route="physics")
        run_local.run_physics_tests(graph_physics)
    
    t_end = time.time()
    
    print(f"\nDa hoan thanh! Thoi gian: {int(t_end - t_start)}s")
    print("Mo file 'detailed_llm_logs.txt' de xem chi tiet cach LLM parse, giai va explain.")

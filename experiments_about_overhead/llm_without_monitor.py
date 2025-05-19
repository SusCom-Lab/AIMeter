from transformers import LlamaForCausalLM, LlamaTokenizer
import torch
import os
from Metrics_Counter import monitor
import time
from datetime import datetime
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
import sys
PID_FILENAME = "python_pid.txt" # The name of the file to store the PID
try:
    # Get the current process's ID
    current_pid = os.getpid()
    # Write the PID to the specified file.
    # This file will be created in the current working directory of the Python script.
    # The shell script changes the CWD to the scenario-specific directory before running Python.
    with open(PID_FILENAME, "w") as pid_file:
        pid_file.write(str(current_pid))
    # Optional: Print a confirmation to standard output (will be logged by the shell script)
    # print(f"Successfully wrote PID {current_pid} to {PID_FILENAME}")
except Exception as e:
    # If any error occurs during PID file creation, print an error message to standard error.
    # This helps in debugging if the shell script cannot find the PID file.
    print(f"Critical Error: Could not write PID to {PID_FILENAME}. Error: {e}", file=sys.stderr)
    sys.exit(1) # Exit the script if PID cannot be written, as monitoring would fail.

model_id = "/home/ldaphome/hhz/workspace/LLM/LLM_Model/Llama-2-7b-hf"
tokenizer = LlamaTokenizer.from_pretrained(model_id)
tokenizer.pad_token = tokenizer.eos_token  # 设置 pad_token 为 eos_token
model = LlamaForCausalLM.from_pretrained(
    model_id,
    local_files_only=True,
    torch_dtype=torch.float16,
    trust_remote_code=True,
)
model = model.to("cuda")  # 现在只会看到 CUDA:0

# 构造input_token_length为20000, batch_size为2的输入
long_segment = (
    "Once upon a time, in a land far away, there was a kingdom surrounded by mountains. "
    "The people of the kingdom lived in harmony with nature, growing their own food, "
    "celebrating festivals, and passing down stories from generation to generation. "
    "Among them was a storyteller who knew every tale from the stars above to the oceans below. "
    "Each night, villagers would gather to hear tales of bravery, sorrow, triumph, and mystery. "
    "This is one of those stories. "
)
eval_prompt1 = long_segment * 400
eval_prompt2 = long_segment * 400
batch_prompts = [eval_prompt1, eval_prompt2]
# 编码输入
model_inputs = tokenizer(batch_prompts, return_tensors="pt", padding=True, truncation=True).to("cuda")
input_ids = model_inputs["input_ids"]
attention_mask = model_inputs["attention_mask"]
input_length = input_ids.shape[1]
batch_size = input_ids.shape[0]
print(f"Batch size: {batch_size}, Input token length: {input_length}")
# 构造一个长度为100的输出
max_new_tokens = 100

try:
    now1 = datetime.now()
    print("Prefill start time:", now1.strftime("%Y-%m-%d %H:%M:%S.") + f"{now1.microsecond // 1000:03d} ms")

    with torch.no_grad():
        prefill_outputs = model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            use_cache=True
        )
    past_key_values = prefill_outputs.past_key_values

    now2 = datetime.now()
    print("Prefill end time:", now2.strftime("%Y-%m-%d %H:%M:%S.") + f"{now2.microsecond // 1000:03d} ms")

    # SLEEP
    print("\nSleeping for 15 seconds before decode...")
    time.sleep(15)

    # DECODE 阶段
    now3 = datetime.now()
    print("Decode start time:", now3.strftime("%Y-%m-%d %H:%M:%S.") + f"{now3.microsecond // 1000:03d} ms")
    generated = input_ids
    for _ in range(max_new_tokens):
        with torch.no_grad():
            next_output = model(
                input_ids=generated[:, -1:],
                attention_mask=torch.ones_like(generated),
                past_key_values=past_key_values,
                use_cache=True
            )
        logits = next_output.logits[:, -1, :]
        next_token_id = torch.argmax(logits, dim=-1, keepdim=True)
        generated = torch.cat([generated, next_token_id], dim=1)
        past_key_values = next_output.past_key_values

    for i in range(batch_size):
        generated_tokens = generated[i][input_length:]
        output_text = tokenizer.decode(generated_tokens, skip_special_tokens=True)
        print(f"\nGenerated continuation for sample {i + 1}:")
        print("=" * 80)
        print(output_text)


    now4 = datetime.now()
    print("Decode end time:", now4.strftime("%Y-%m-%d %H:%M:%S.") + f"{now4.microsecond // 1000:03d} ms")
    print("\nGenerated continuation:")
    print("=" * 80)
    print(output_text)

finally:
    # 确保监控器停止
    # 写入 duration_log.csv
    import csv
    duration = (now4 - now1).total_seconds()
    csv_file = "duration_log.csv"
    file_exists = os.path.isfile(csv_file)

    current_id = 1
    if file_exists:
        with open(csv_file, mode='r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                current_id = int(rows[-1]['id']) + 1

    with open(csv_file, mode='a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'time'])
        if not file_exists:
            writer.writeheader()
        writer.writerow({'id': current_id, 'time': duration})
        
    print("\nMonitoring stopped.")
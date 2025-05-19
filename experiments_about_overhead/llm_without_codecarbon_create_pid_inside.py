from transformers import LlamaForCausalLM, LlamaTokenizer
import torch
import os
# from Metrics_Counter import monitor # Assuming monitor might be used later
import time
from datetime import datetime
import sys
import csv # Import csv at the top

# Define constants at the module level if they are used in the main block or multiple functions
PID_FILENAME = "python_pid.txt" # The name of the file to store the PID
MODEL_ID = "/home/ldaphome/hhz/workspace/LLM/LLM_Model/Llama-2-7b-hf"

def run_llama_inference_and_log():
    """
    Runs Llama 2 inference for prefill and decode stages,
    and logs the total duration.
    Also writes the current PID to a file.
    """
    # PID writing logic moved here:
    try:
        current_pid = os.getpid()
        with open(PID_FILENAME, "w") as pid_file:
            pid_file.write(str(current_pid))
        print(f"Successfully wrote PID {current_pid} to {PID_FILENAME}")
    except Exception as e:
        print(f"Critical Error: Could not write PID to {PID_FILENAME}. Error: {e}", file=sys.stderr)
        sys.exit(1) # Exit if PID cannot be written

    os.environ["CUDA_VISIBLE_DEVICES"] = "0"

    print(f"Loading tokenizer from: {MODEL_ID}")
    tokenizer = LlamaTokenizer.from_pretrained(MODEL_ID)
    tokenizer.pad_token = tokenizer.eos_token  # 设置 pad_token 为 eos_token

    print(f"Loading model from: {MODEL_ID}")
    model = LlamaForCausalLM.from_pretrained(
        MODEL_ID,
        local_files_only=True,
        torch_dtype=torch.float16,
        trust_remote_code=True,
    )
    model = model.to("cuda")  # 现在只会看到 CUDA:0
    print("Model loaded successfully to CUDA.")

    # 构造input_token_length, batch_size为2的输入
    long_segment = (
        "Once upon a time, in a land far away, there was a kingdom surrounded by mountains. "
        "The people of the kingdom lived in harmony with nature, growing their own food, "
        "celebrating festivals, and passing down stories from generation to generation. "
        "Among them was a storyteller who knew every tale from the stars above to the oceans below. "
        "Each night, villagers would gather to hear tales of bravery, sorrow, triumph, and mystery. "
        "This is one of those stories. "
    )
    # Note: Original code aims for input_token_length of 20000.
    # The tokenizer's max length for Llama is typically 4096.
    # Multiplying long_segment * 400 will create a very long string,
    # which will be truncated by the tokenizer if truncation=True.
    # For Llama-2-7b, context length is 4096.
    # To get closer to a specific token length, you'd typically repeat tokens or find text of that length.
    # The current approach will likely result in input_length being the model's max sequence length (e.g., 4096).
    print("Constructing input prompts...")
    eval_prompt1 = long_segment * 40 # Adjusted for typical max length; original was 400
    eval_prompt2 = long_segment * 40 # Adjusted for typical max length; original was 400
    batch_prompts = [eval_prompt1, eval_prompt2]

    # 编码输入
    print("Tokenizing inputs...")
    model_inputs = tokenizer(batch_prompts, return_tensors="pt", padding=True, truncation=True, max_length=4096).to("cuda") # Added max_length
    input_ids = model_inputs["input_ids"]
    attention_mask = model_inputs["attention_mask"]
    input_length = input_ids.shape[1]
    batch_size = input_ids.shape[0]
    print(f"Batch size: {batch_size}, Input token length (after tokenization): {input_length}")

    # 构造一个长度为100的输出
    max_new_tokens = 100
    output_text = "" # Initialize output_text to ensure it's defined

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
        prefill_duration = (now2 - now1).total_seconds()
        print(f"Prefill duration: {prefill_duration:.3f} seconds")

        # # SLEEP
        # print("\nSleeping for 15 seconds before decode...")
        # time.sleep(15)

        # DECODE 阶段
        now3 = datetime.now()
        print("Decode start time:", now3.strftime("%Y-%m-%d %H:%M:%S.") + f"{now3.microsecond // 1000:03d} ms")

        generated_sequences = [] # Store full generated sequences for each batch item

        # For this example, we'll generate for the whole batch token by token
        # which is more standard. The original loop structure was a bit ambiguous for batch processing.
        # Let's refine the decode loop for clarity with batching.

        generated_batch = input_ids.clone() # Start with the input_ids for the whole batch
        current_batch_past_key_values = past_key_values

        for _ in range(max_new_tokens):
            with torch.no_grad():
                # For batch decoding, the input_ids for the next token should be the last token of each sequence in the batch
                next_tokens_to_feed = generated_batch[:, -1:]

                # The attention mask needs to be extended for each new token
                # For simplicity in autoregressive generation, often a full attention mask is used for the K/V cache.
                # The model internally handles causal masking for new tokens.
                # Or, we can create a new attention mask for the single new token.
                current_attention_mask = torch.ones((generated_batch.shape[0], generated_batch.shape[1] + next_tokens_to_feed.shape[1] -1), device="cuda") # Adjusted attention mask size for current input + next token

                next_output = model(
                    input_ids=next_tokens_to_feed, # Feed only the last token of each sequence
                    attention_mask=current_attention_mask[:, -next_tokens_to_feed.shape[1]:], # Pass attention mask for the new token(s)
                    past_key_values=current_batch_past_key_values,
                    use_cache=True
                )
                logits = next_output.logits[:, -1, :] # Get logits for the last token
                next_token_ids = torch.argmax(logits, dim=-1, keepdim=True)
                generated_batch = torch.cat([generated_batch, next_token_ids], dim=1)
                current_batch_past_key_values = next_output.past_key_values

        now4 = datetime.now() # Mark end of generation for all batches
        print("Decode end time:", now4.strftime("%Y-%m-%d %H:%M:%S.") + f"{now4.microsecond // 1000:03d} ms")
        decode_duration = (now4 - now3).total_seconds()
        print(f"Decode duration: {decode_duration:.3f} seconds")

        for i in range(batch_size):
            generated_tokens = generated_batch[i][input_length:] # Get only the newly generated tokens
            output_text = tokenizer.decode(generated_tokens, skip_special_tokens=True)
            print(f"\nGenerated continuation for sample {i + 1}:")
            print("=" * 80)
            print(output_text)

        # The original code only prints the last output_text outside the loop.
        # The loop above now prints each sample's output.
        # If you need the last one specifically:
        if batch_size > 0:
            last_generated_tokens = generated_batch[-1][input_length:]
            last_output_text = tokenizer.decode(last_generated_tokens, skip_special_tokens=True)
            print("\nLast generated continuation (for reference):")
            print("=" * 80)
            print(last_output_text)
        else:
            last_output_text = ""


    finally:
        # Ensure monitoring stops if it was started (currently no monitor.start() in the active code)
        # monitor.stop() # Example if monitor was used

        # 写入 duration_log.csv
        # Ensure now1 and now4 are defined. If an exception occurs before now4, this will error.
        # It's better to calculate duration if now4 is available.
        if 'now1' in locals() and 'now4' in locals():
            duration = (now4 - now1).total_seconds()
            csv_file = "duration_log.csv"
            file_exists = os.path.isfile(csv_file)
            current_id_val = 1 # Renamed to avoid conflict with built-in id

            if file_exists:
                try:
                    with open(csv_file, mode='r', encoding='utf-8') as f_read:
                        reader = csv.DictReader(f_read)
                        rows = list(reader)
                        if rows: # Check if rows is not empty
                            current_id_val = int(rows[-1]['id']) + 1
                except Exception as e_csv_read:
                    print(f"Error reading CSV to determine ID: {e_csv_read}. Starting ID from 1.", file=sys.stderr)


            try:
                with open(csv_file, mode='a', newline='', encoding='utf-8') as f_append:
                    writer = csv.DictWriter(f_append, fieldnames=['id', 'time'])
                    if not file_exists or (file_exists and os.path.getsize(csv_file) == 0): # Check if new file or empty
                        writer.writeheader()
                    writer.writerow({'id': current_id_val, 'time': duration})
                print(f"\nDuration {duration:.3f} seconds logged to {csv_file} with id {current_id_val}")
            except Exception as e_csv_write:
                print(f"Error writing to CSV: {e_csv_write}", file=sys.stderr)
        else:
            print("Could not log duration as start or end time was not captured.", file=sys.stderr)

        print("\nMonitoring (placeholder) stopped. Script finished.")


if __name__ == "__main__":
    # Call the main inference and logging function
    run_llama_inference_and_log()
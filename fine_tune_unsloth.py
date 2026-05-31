# Kaggle Fine-Tuning Script using Unsloth
# This script is designed to run in a Kaggle Notebook with a GPU (e.g., T4 x2 or L4) 
# to fine-tune a model on tax code and export it directly to GGUF format for Ollama.

import os

# ==========================================
# 1. Install Unsloth & Dependencies
# ==========================================
# Run these in your Kaggle notebook cell before importing:
# !pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
# !pip install --no-deps trl peft accel package_name
# !pip install xformers

from unsloth import FastLanguageModel
import torch
from datasets import Dataset
from trl import SFTTrainer
from transformers import TrainingArguments

# ==========================================
# 2. Configuration & Model Loading
# ==========================================
max_seq_length = 4096 # Supports rope scaling automatically
dtype = None # None for auto-detection (Float16/Bfloat16 based on GPU)
load_in_4bit = True # Use 4bit quantization to fit in low-memory environments

# Hugging Face Repository to upload the GGUF model to (change this to your desired repo)
HF_REPO_ID = "nswitzer/gemma2-9b-tax-audit-GGUF"

# We load Gemma-2 9B Instruct as our base model
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/gemma-2-9b-it-bnb-4bit",
    max_seq_length = max_seq_length,
    dtype = dtype,
    load_in_4bit = load_in_4bit,
)

# ==========================================
# 3. Configure LoRA Adapters
# ==========================================
model = FastLanguageModel.get_peft_model(
    model,
    r = 16, # Choose any number > 0. Suggested: 8, 16, 32, 64, 128
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj"],
    lora_alpha = 16,
    lora_dropout = 0, # Optimized for 0
    bias = "none",    # Optimized for "none"
    use_gradient_checkpointing = "unsloth", # 4x longer contexts, zero memory bloat
    random_state = 3407,
    use_rslora = False,
    loftq_config = None,
)

# ==========================================
# 4. Formulate Dataset (Tax Rules & Audits)
# ==========================================
# Prompt template for formatting the training examples (Gemma 2 Chat Template)
prompt_template = """<bos><start_of_turn>user
You are an expert tax auditor specializing in the Internal Revenue Code (IRC). Analyze the financial scenario and apply the correct tax rules.

Scenario: {}<end_of_turn>
<start_of_turn>model
Analysis and Ruling: {}<end_of_turn>"""

# Sample dataset of IRC tax rulings. Replace this with your full corpus.
# For best results, scrape/parse the IRS manuals or tax code publications.
dataset_data = [
    {
        "instruction": "Taxpayer has W-2 income of $480,000 and claims a $5,000 loss on a residential rental property in Michigan. The taxpayer actively participated. Can they deduct the loss?",
        "ruling": "Under IRC Section 469 and IRS Publication 925, passive losses from rental real estate are subject to phase-out. The $25,000 active participation allowance is reduced by $0.50 for every $1.00 of Modified Adjusted Gross Income (MAGI) over $100,000. For a taxpayer with MAGI of $480,000, the allowance is fully phased out (the threshold is completely exhausted at $150,000). Thus, the $5,000 loss cannot be deducted against W-2 income and must be suspended and carried forward on Form 8582."
    },
    {
        "instruction": "A side business has reported losses for 5 consecutive years. Under audit, the taxpayer states it is a Sole Proprietorship. How are expenses handled?",
        "ruling": "Under IRC Section 183 (Hobby Loss Rules), if a business fails to produce a profit in at least 3 out of 5 consecutive years, it is presumed to be a hobby. Under the TCJA, all miscellaneous itemized deductions subject to the 2% AGI floor are suspended (IRC § 67(g)). Therefore, all hobby expenses are completely non-deductible. The taxpayer must report 100% of the gross receipts as 'Other Income' on Form 1040, Schedule 1, Part I, Line 8z, and cannot offset this income with any business expenses."
    },
    {
        "instruction": "Taxpayer filed for an extension (Form 4868) on April 15. The return is filed on October 10 with a remaining tax liability of $10,000. What penalties apply?",
        "ruling": "An extension of time to file is not an extension of time to pay. Since the remaining tax liability of $10,000 was unpaid on April 15, interest and the Failure-to-Pay penalty under IRC § 6651(a)(2) apply from April 15 until the date paid. The penalty is 0.5% of the unpaid tax for each month or fraction of a month (approx. 6 months = 3.0%). Since the return was filed before the October 15 extended deadline, no Failure-to-File penalty (5% per month) applies."
    },
    {
        "instruction": "What is the MACRS depreciation parameters for a residential apartment building?",
        "ruling": "Under IRS Publication 946, residential rental property is depreciated over a recovery period of 27.5 years under the General Depreciation System (GDS) using the Straight-Line method and the Mid-Month convention. Note that the cost of land must be subtracted from the purchase price, as land is non-depreciable."
    }
]

def format_prompts(batch):
    texts = []
    for inst, rule in zip(batch["instruction"], batch["ruling"]):
        text = prompt_template.format(inst, rule)
        texts.append(text)
    return {"text": texts}

# Convert to HuggingFace Dataset format
dataset = Dataset.from_list(dataset_data)
dataset = dataset.map(format_prompts, batched = True)

# ==========================================
# 5. Training Setup
# ==========================================
trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    dataset_num_proc = 2,
    packing = False, # Speed up training for short sequences
    args = TrainingArguments(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,
        warmup_steps = 5,
        max_steps = 60, # Increase this for larger datasets (e.g., 500-1000)
        learning_rate = 2e-4,
        fp16 = not torch.cuda.is_bf16_supported(),
        bf16 = torch.cuda.is_bf16_supported(),
        logging_steps = 1,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        seed = 3407,
        output_dir = "outputs",
    ),
)

# Run the training
trainer_stats = trainer.train()

# ==========================================
# 5.5. Evaluate Model Accuracy (In-Memory)
# ==========================================
print("\n--- Running In-Memory Accuracy Evaluation ---")
FastLanguageModel.for_inference(model) # Enable native 2x faster inference

TEST_SUITE = [
    {
        "id": "T1_PASSIVE_LOSS",
        "description": "High-income passive rental loss phase-out test",
        "prompt": "Taxpayer has W-2 income of $480,000 and claims a $5,000 loss on an active rental property in Michigan. Can they deduct this loss?",
        "required_keywords": ["phase-out", "suspended", "Form 8582"],
        "negative_keywords": ["deduct in full", "allowable deduction"]
    },
    {
        "id": "T2_MACRS_DEPR",
        "description": "Residential rental MACRS depreciation parameters test",
        "prompt": "What MACRS depreciation rules and recovery period apply to a residential rental property?",
        "required_keywords": ["27.5", "straight-line", "mid-month", "land"],
        "negative_keywords": ["39 years", "15 years", "double declining"]
    },
    {
        "id": "T3_HOBBY_LOSS",
        "description": "Sole Proprietorship with persistent losses (Hobby classification)",
        "prompt": "A taxpayer has a side business that reported losses for 5 consecutive years. Under TCJA, can they deduct expenses?",
        "required_keywords": ["hobby", "non-deductible", "Schedule 1", "183"],
        "negative_keywords": ["Schedule C deduction", "deduct business expense"]
    },
    {
        "id": "T4_SAFE_HARBOR",
        "description": "High-income safe harbor estimated tax payments",
        "prompt": "The taxpayer had an AGI of $480,000 last year. What percentage of last year's tax liability do they need to pay to meet the safe harbor rule?",
        "required_keywords": ["110%", "safe harbor"],
        "negative_keywords": ["90%", "100%"]
    },
    {
        "id": "T5_EXTENSION_LATE_PAY",
        "description": "Form 4868 late payment vs late filing rules",
        "prompt": "If a taxpayer files Form 4868 for an extension on April 15 but pays the remaining tax in October, do they face any penalties?",
        "required_keywords": ["failure-to-pay", "interest", "0.5%"],
        "negative_keywords": ["failure-to-file penalty", "5% per month"]
    }
]

passed_tests = 0
total_tests = len(TEST_SUITE)

for i, test in enumerate(TEST_SUITE, 1):
    print(f"\n[{i}/{total_tests}] Running: {test['description']}")
    
    # Format the prompt using the Gemma 2 chat template structure
    formatted_prompt = prompt_template.format(test["prompt"], "")
    
    inputs = tokenizer([formatted_prompt], return_tensors = "pt").to("cuda")
    
    # Generate output tokens
    outputs = model.generate(
        **inputs, 
        max_new_tokens = 512, 
        use_cache = True,
        do_sample = False  # greedy search
    )
    
    # Decode only the newly generated tokens
    input_length = inputs.input_ids.shape[1]
    generated_tokens = outputs[0][input_length:]
    decoded_response = tokenizer.decode(generated_tokens, skip_special_tokens = True)
    response_lower = decoded_response.lower()
    
    # Evaluate keywords
    missed_keywords = []
    for kw in test['required_keywords']:
        if kw.lower() not in response_lower:
            missed_keywords.append(kw)
            
    found_negatives = []
    for kw in test['negative_keywords']:
        if kw.lower() in response_lower:
            found_negatives.append(kw)
            
    if not missed_keywords and not found_negatives:
        print("Result: ✅ PASSED")
        passed_tests += 1
    else:
        print("Result: ❌ FAILED")
        if missed_keywords:
            print(f"  - Missed required keywords: {missed_keywords}")
        if found_negatives:
            print(f"  - Contained forbidden words: {found_negatives}")
            
    print(f"Model Response Preview:\n{decoded_response[:200]}...")
    print("-" * 50)

accuracy = (passed_tests / total_tests) * 100
print(f"\nIn-Memory Accuracy: {accuracy:.2f}% ({passed_tests}/{total_tests} passed)\n")

# ==========================================
# 6. Export directly to GGUF and Upload to Hugging Face
# ==========================================
# Retrieve Hugging Face token from Kaggle Secrets
try:
    from kaggle_secrets import UserSecretsClient
    user_secrets = UserSecretsClient()
    hf_token = user_secrets.get_secret("HF_TOKEN")
except Exception as e:
    print(f"Could not load HF_TOKEN from Kaggle Secrets: {e}")
    hf_token = None

# Unsloth supports direct saving to GGUF format!
# This will output a file named 'tax-audit-model-Q4_K_M.gguf' locally.
print("Saving model locally in GGUF format...")
model.save_pretrained_gguf(
    "tax-audit-model",
    tokenizer,
    quantization_method = "q4_k_m" # High quality 4-bit quantization
)

# Upload the generated GGUF file to your Hugging Face Hub repository
if hf_token:
    print("Uploading GGUF model to Hugging Face Hub...")
    from huggingface_hub import HfApi
    api = HfApi(token=hf_token)
    
    file_name = "tax-audit-model-Q4_K_M.gguf"
    
    try:
        # Create repo if it doesn't exist
        try:
            api.create_repo(repo_id=HF_REPO_ID, repo_type="model", exist_ok=True)
        except Exception as e:
            print(f"Note: Could not check/create repository: {e}")
            
        api.upload_file(
            path_or_fileobj=file_name,
            path_in_repo=file_name,
            repo_id=HF_REPO_ID,
            repo_type="model",
        )
        print(f"Successfully uploaded {file_name} to https://huggingface.co/{HF_REPO_ID}!")
    except Exception as e:
        print(f"Failed to upload model to Hugging Face: {e}")
else:
    print("Skipping Hugging Face upload as HF_TOKEN was not found in Kaggle Secrets.")

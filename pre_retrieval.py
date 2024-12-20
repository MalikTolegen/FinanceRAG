import os
import pdb
import re
import shutil
import json
from pathlib import Path
from dotenv import load_dotenv
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

def initialize_llm():
    """
    Initialize a Hugging Face model (T5 in this case).
    """
    model_name = "t5-small"  # You can change this to any other model like `t5-base`, `t5-large`, etc.
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
    return model, tokenizer


model, tokenizer = initialize_llm()

def generate_text(model, tokenizer, prompt):
    """
    Use the Hugging Face model to generate text based on the input prompt.
    """
    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, padding=True)
    outputs = model.generate(inputs["input_ids"], max_length=150)
    return tokenizer.decode(outputs[0], skip_special_tokens=True)

def clean_text(text):
    """
    Replace all Unicode escape sequences (e.g., \u2019, \u0080) with a space.
    """
    return re.sub(r"(\\u[0-9A-Fa-f]{4})+", " ", text)


def load_jsonl(file_path):
    """
    Load a JSONL file and return its content as a list of dictionaries.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found at {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return [json.loads(clean_text(line.strip())) for line in f]


def save_jsonl(file_path, data, ensure_ascii=True):
    """
    Save a list of dictionaries to a JSONL file.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=ensure_ascii) + "\n")


def load_prompt(subset, key="queries"):
    """
    Load prompt template for the specified subset.
    """
    prompt_path = Path("./prompt.json")
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found at {prompt_path}")
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompts = json.load(f)["pre_retrieval"][key]
    if subset not in prompts:
        raise ValueError(f"Prompt not found for subset '{subset}'")
    return prompts[subset]


def _extract_table_from_corpus(c_text, subset):
    """
    Extracts corpus tables and a sentence before each table.
    """
    lines = c_text.split("\n")
    results = []
    table_start = None

    # Iterate through lines to find all tables
    for i, line in enumerate(lines):
        if line.startswith("| "):
            if table_start is None:
                table_start = i  # Start of a new table

            # Check if this is the end of the table block
            if i + 1 == len(lines) or not lines[i + 1].startswith("| "):
                # Extract the sentence immediately before the table
                before_sentence = lines[table_start - 1] if table_start > 0 else ""
                
                # Extract the table content
                table_content = "\n".join(lines[table_start:i + 1])
                after_sentence = ""
                if i + 1 < len(lines) and not lines[i + 1].startswith("| "):
                    after_sentence = lines[i + 1]

                # Extract Table Content only
                result = f"{table_content}".strip()
                results.append(result)

                # Reset for the next table
                table_start = None

    # Return combined results if tables are found, otherwise handle based on subset
    if results:
        return "\n\n".join(results)
    else:
        # Handle cases where no table is found, based on the subset
        parts = c_text.split("\n\n")
        if subset in {"TATQA", "FinQA", "ConvFinQA"}:
            return parts[-1] if subset == "TATQA" else parts[1] if len(parts) > 1 else parts[0]
        elif subset == "MultiHiertt":
            return c_text
        else:
            raise ValueError("Error: subset does not exist.")


def expand_queries(subset, dataset_dir, llm, overwrite=False):
    """
    Expands data (queries or corpus) for a given subset using the LLM.
    
    We provides expanded queries generated through the LLM to ensure exact reproducibility.
    However, if you wish to regenerate the expanded queries, set `overwrite=True`.
    """
    data = load_jsonl(Path(f"{dataset_dir}/{subset}/queries.jsonl"))
    prompt_template = load_prompt(subset, "queries")

    expanded_queries = []
    for item in data:
        item_text = item["text"]
        prompt = f"{prompt_template}\n\nQuery: {item_text}"
        new_text = generate_text(model, tokenizer, prompt)
        expanded_queries.append(
            {
                "_id": item["_id"],
                "title": item["title"],
                "text": f"{item_text}\n\n{new_text}",
            }
        )

    save_path = Path(f"{dataset_dir}/{subset}/queries_prep.jsonl")
    if not save_path.is_file() or overwrite:
        save_jsonl(save_path, expanded_queries)
    

def compress_corpus(subset, dataset_dir):
    """
    Compress specific sections of corpus text for given subsets.
    """
    corpus = load_jsonl(Path(f"{dataset_dir}/{subset}/corpus.jsonl"))
    for item in corpus:
        item["text"] = _extract_table_from_corpus(item["text"], subset)
    save_jsonl(Path(f"{dataset_dir}/{subset}/corpus_prep.jsonl"), corpus)


def copy_corpus(subset, dataset_dir):
    from_path = os.path.join(dataset_dir, subset, 'corpus.jsonl')
    to_path = os.path.join(dataset_dir, subset, 'corpus_prep.jsonl')
    shutil.copy(from_path, to_path)

def pre_retrieval(dataset_dir):
    # Initialize Hugging Face model and tokenizer
    model, tokenizer = initialize_llm()

    subsets = [
        "FinanceBench",
        "FinDER",
        "FinQABench",
        "MultiHiertt",
        "ConvFinQA",
        "TATQA",
        "FinQA",
    ]

    for subset in subsets:
        try:
            print(f"Pre-retrieval for '{subset}' initiating...")
            expand_queries(subset, dataset_dir, model, tokenizer)  # Pass the model and tokenizer to expand_queries
            if subset == "MultiHiertt":
                compress_corpus(subset, dataset_dir)
            else:
                copy_corpus(subset, dataset_dir)
            print(f"Pre-retrieval for '{subset}' completed.")

        except (FileNotFoundError, ValueError) as e:
            print(f"Pre-retrieval for '{subset}' Error : {e}")


if __name__ == "__main__":

    dataset_dir = "./dataset"
    pre_retrieval(dataset_dir)

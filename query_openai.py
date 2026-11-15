#!/usr/bin/env python3
import os
import sys
from openai import OpenAI

def main():
    if len(sys.argv) != 4:
        print("Expected three arguments: <prompt_file> <input_file> <output_file>")
        sys.exit(1)

    prompt_file = sys.argv[1]
    input_file = sys.argv[2]
    output_file = sys.argv[3]

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable not set.")
        sys.exit(1)
    client = OpenAI(api_key=api_key)

    # Read input files
    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt = f.read()
    with open(input_file, "r", encoding="utf-8") as f:
        input = f.read()

    # Query OpenAI
    print(f"Querying openai with {len(input)} bytes...")
    response = client.chat.completions.create(
        model="gpt-6-luna",  # "gpt-5", "gpt-5-mini", etc
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": input}
        ],
    )
    result_text = response.choices[0].message.content.strip()

    # Write output to file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(result_text)
    print(f"✅ Output written to {output_file}")

if __name__ == "__main__":
    main()

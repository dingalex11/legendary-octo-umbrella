import argparse
import csv
import json
import re
from pathlib import Path
from pypdf import PdfReader


def extract_clean_text(pdf_path: str) -> str:
    """Extracts text from PDF and removes headers, footers, and page numbers."""
    reader = PdfReader(pdf_path)
    pages_text = []

    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages_text.append(text)

    full_text = "\n".join(pages_text)

    # 1. Remove page footers like "Middle School Round 1 Page 3"
    full_text = re.sub(
        r"(?:High|Middle)\s+School\s+Round\s+\d+\s+Page\s+\d+",
        "",
        full_text,
        flags=re.IGNORECASE,
    )

    # 2. Remove standalone "Page X" or "Round X Page Y"
    full_text = re.sub(
        r"Page\s+\d+", "", full_text, flags=re.IGNORECASE
    )

    # 3. Clean up common formatting noise
    full_text = re.sub(r"\r\n|\r", "\n", full_text)

    # 4. Remove pronunciation guides like (read as: prōe-KAHR-ee-ōets)
    full_text = re.sub(
        r"\(read as:.*?\)", "", full_text, flags=re.IGNORECASE
    )

    return full_text


def parse_science_bowl_text(raw_text: str) -> list:
    """Uses a robust block-matching regex to capture diverse NSB PDF formats."""
    questions = []

    # Pattern explanation:
    # 1. Matches TOSSUP/BONUS headers (e.g., TOSSUP 1, 1) LIFE SCIENCE, TOSS-UP)
    # 2. Captures Category and Question Type (Short Answer / Multiple Choice)
    # 3. Captures Question text up to "ANSWER:"
    # 4. Captures Answer text up to the next TOSSUP/BONUS header or end of file
    block_pattern = re.compile(
        r"(?:TOSSUP|TOSS-UP|BONUS)\s*\d*[\.\)]?\s*"  # Header marker
        r"(?:([A-Za-z\s]+?)\s*[,:]?\s*)?"  # Optional Category (e.g. CHEMISTRY)
        r"(Short Answer|Multiple Choice|MULTIPLE CHOICE|SHORT ANSWER)\s+"  # Type
        r"(.*?)"  # Question body
        r"ANSWER:\s*(.*?)"  # Answer line
        r"(?=(?:TOSSUP|TOSS-UP|BONUS|\Z))",  # Lookahead for next question or EOF
        re.DOTALL | re.IGNORECASE,
    )

    matches = block_pattern.findall(raw_text)

    current_set = None

    for category, q_type, q_body, answer in matches:
        # Clean text artifacts
        category_clean = category.strip().title() if category else "General Science"
        q_type_clean = q_type.strip().title()

        # Clean whitespace and newlines from body and answer
        q_body_clean = re.sub(r"\s+", " ", q_body.strip())
        answer_clean = re.sub(r"\s+", " ", answer.strip())

        # Strip internal tags from answer if present (e.g., [SB] MECH 7 or [ZZ] WAVE 4)
        answer_clean = re.sub(r"\[[A-Z0-9\s]+\]$", "", answer_clean).strip()

        # Build clean formatted text
        formatted_question = (
            f"{category_clean}. {q_type_clean}. {q_body_clean}"
        )

        # Determine if this block is a Tossup or Bonus by checking the preceding text match
        # If we don't have an active set or if this is a Tossup, create a new container
        if current_set is None:
            current_set = {
                "category": category_clean,
                "tossup_text": formatted_question,
                "tossup_answer": answer_clean,
                "bonus_text": "",
                "bonus_answer": "",
            }
        else:
            # Attach as Bonus
            current_set["bonus_text"] = formatted_question
            current_set["bonus_answer"] = answer_clean
            questions.append(current_set)
            current_set = None

    # Append any remaining unpaired question
    if current_set:
        questions.append(current_set)

# Strip trailing footer remnants from answers
    answer_clean = re.sub(
        r"\s*(?:High|Middle)?\s*School\s*Round.*$",
        "",
        answer_clean,
        flags=re.IGNORECASE,
    ).strip()
    answer_clean = re.sub(
        r"\s*Page\s*\d+.*$", "", answer_clean, flags=re.IGNORECASE
    ).strip()

    return questions


# Replace the main() function in pdf_to_bank.py with this:

def main():
    parser = argparse.ArgumentParser(
        description="Flexible NSB PDF Question Extractor"
    )
    parser.add_argument("pdf_path", type=str, help="Path to PDF question set")
    parser.add_argument(
        "--format", choices=["json", "csv"], default="json", help="Export format"
    )

    args = parser.parse_args()
    pdf_file = Path(args.pdf_path)

    if not pdf_file.exists():
        print(f"Error: Could not find file {args.pdf_path}")
        return

    print(f"Parsing '{pdf_file.name}'...")
    
    # We read the raw text and parse it
    raw_text = extract_clean_text(str(pdf_file))
    parsed = parse_science_bowl_text(raw_text)

    print(f"Successfully extracted {len(parsed)} Question Sets!")

    # 🟢 Ensure the data folder exists
    data_folder = Path(__file__).parent.parent / "data"
    data_folder.mkdir(exist_ok=True)

    # 🟢 Save the output directly into the data/ folder
    output_filename = data_folder / f"{pdf_file.stem}_bank.{args.format}"

    if args.format == "json":
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(parsed, f, indent=2)
    else:
        with open(output_filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "category",
                    "tossup_text",
                    "tossup_answer",
                    "bonus_text",
                    "bonus_answer",
                ],
            )
            writer.writeheader()
            writer.writerows(parsed)
            
    print(f"✅ Saved to: {output_filename.resolve()}")


if __name__ == "__main__":
    main()
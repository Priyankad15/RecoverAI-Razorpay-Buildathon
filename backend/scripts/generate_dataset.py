"""
Generates the synthetic failed-payment dataset and writes it to
data/raw/synthetic_payments.csv, printing a data-quality report.

Usage (from the backend/ directory):
    python -m scripts.generate_dataset [--n-records 3000] [--seed 42]
"""

import argparse
from pathlib import Path

from app.ml.data_generation import generate_synthetic_dataset, validate_dataset

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
OUTPUT_PATH = REPO_ROOT / "data" / "raw" / "synthetic_payments.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic failed-payment dataset")
    parser.add_argument("--n-records", type=int, default=3000, help="Number of records to generate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    if args.n_records < 1000:
        raise ValueError("n_records must be at least 1000 per the Phase 2 requirement.")

    df = generate_synthetic_dataset(n_records=args.n_records, seed=args.seed)

    report = validate_dataset(df)
    report.print_report()

    if not report.is_clean():
        raise RuntimeError("Generated dataset failed data-quality validation - see report above.")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"\nDataset written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

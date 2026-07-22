# Rosa forecast lead-time archive (Stage 0)

One append-only JSONL per buoy under `archive/`; rows are
`{run, valid, hs, tp, dir}`. Written by .github/workflows/rosa-archive.yml.
Score it with: rosa-pipeline verify --buoy <id> --archive --archive-dir <this>/archive

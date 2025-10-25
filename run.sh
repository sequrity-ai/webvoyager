#!/bin/bash
uv run --env-file ../.env.local python run.py \
    --test_file ./data/tasks_test.jsonl \
    --headless \
    --max_iter 15 \
    --max_attached_imgs 3 \
    --temperature 1 \
    --fix_box_color \
    --seed 42 > test_tasks.log &

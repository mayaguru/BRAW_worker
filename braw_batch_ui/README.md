# BRAW Batch Export UI

Segmented batch export tool for Blackmagic RAW files with automatic retry system.

## Features

- **Segmented Processing**: Small chunks for better reliability
- **Automatic Retry**: Failed jobs automatically retried in next segments
- **Real-time Stats**: Track total/completed/failed/pending jobs
- **Persistent State**: Failed jobs saved and can be resumed later

## Usage

### Run UI

```bash
cd d:\_DEV\Braw\braw_batch_ui
uv run python braw_batch_ui\main.py
```

Or use parent directory batch file: `run_batch_ui.bat`

## Settings

- **Segment Size**: Number of jobs per segment (default: 10)
- **Delay (ms)**: Delay between CLI invocations (default: 100ms)
- **Max Retries**: Maximum retry attempts per job (default: 3)

## How It Works

1. All jobs are created at start
2. Process jobs in segments (e.g., 10 jobs per segment)
3. Each segment prioritizes failed jobs from previous segments
4. After max retries, failed jobs are marked as "given up"
5. Failed jobs saved to `failed_jobs.json`

## Example

```
Segment #1: 10 new → 2 fail
Segment #2: 2 retry + 8 new → 1 more fail
Segment #3: 3 retry + 7 new → all succeed
```

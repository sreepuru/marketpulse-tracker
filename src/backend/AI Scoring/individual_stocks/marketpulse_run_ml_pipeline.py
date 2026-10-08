"""
MarketPulse - Step-by-Step AI + PIT + LightGBM Pipeline Runner

Execution order:
1. Deterministic mapping candidate generation (V2.2)
2. Mapping Agent decision (V2.0.2)
3. PIT ML dataset build
2. AI prediction for every market_news event without an AI prediction
3. PIT ML dataset refresh so newly-created AI event fields reach ML
4. Event-level feature build/update
5. LightGBM +1D training
6. LightGBM +5D training
7. LightGBM +10D training
8. LightGBM +1D/+5D/+10D scoring
11. Final read-only database coverage audit

PIT is intentionally the first step, as requested.
Mapping runs before ML so security identity is available to downstream features/scoring.
The second PIT pass is intentional because the PIT builder reads the latest
AI event type/status and writes those fields into market_news_ml_samples.
This runner invokes the canonical scripts; it does not replace them.

Run from project root:
    python src/backend/marketpulse_run_ml_pipeline.py

Useful options:
    --skip-ai
    --skip-pit-refresh
    --skip-features
    --skip-training
    --skip-scoring
    --rerun-scoring
    --pit-limit 100
    --ai-limit 100
    --ai-sleep 0.1
    --feature-limit 1000
    --start-id 1 --end-id 10000
    --pause 3
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import tempfile
import psycopg
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[4]

BACKEND_DIR = PROJECT_ROOT / "src" / "backend"
AGENTS_DIR = BACKEND_DIR / "agents"
AI_SCORING_DIR = BACKEND_DIR / "AI Scoring" / "individual_stocks"

MAPPING_ENGINE_SCRIPT = AGENTS_DIR / "marketpulse_mapping_agent_v2_2.py"
MAPPING_AGENT_SCRIPT = AGENTS_DIR / "marketpulse_mapping_agent.py"

PIT_SCRIPT = AI_SCORING_DIR / "marketpulse_build_ml_dataset_pit_v2.py"
AI_SCRIPT = BACKEND_DIR / "marketpulse_ai_predict_all_events.py"
FEATURE_SCRIPT = AI_SCORING_DIR / "marketpulse_build_event_features.py"
TRAIN_SCRIPT = AI_SCORING_DIR / "marketpulse_train_lightgbm_1d.py"
SCORE_SCRIPT = AI_SCORING_DIR / "marketpulse_score_lightgbm_1d.py"



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Run the complete MarketPulse AI + PIT + LightGBM pipeline.'
    )
    parser.add_argument('--skip-mapping', action='store_true',
                        help='Skip deterministic mapping candidate generation and Mapping Agent.')
    parser.add_argument('--skip-agent', action='store_true',
                        help='Skip Mapping Agent while still allowing deterministic candidate generation.')
    parser.add_argument('--mapping-limit', type=int, default=None,
                        help='Optional identity-group limit for deterministic mapping.')
    parser.add_argument('--agent-limit', type=int, default=None,
                        help='Optional identity-group limit for Mapping Agent.')
    parser.add_argument('--max-candidates', type=int, default=20,
                        help='Maximum candidates retained/considered per identity group.')
    parser.add_argument('--max-agent-steps', type=int, default=3,
                        help='Maximum research steps per Mapping Agent decision.')
    parser.add_argument('--skip-ai', action='store_true',
                        help='Skip all-feed AI prediction.')
    parser.add_argument('--skip-pit-refresh', action='store_true',
                        help='Skip the PIT refresh after AI prediction.')
    parser.add_argument('--skip-features', action='store_true',
                        help='Skip event-level feature build/update.')
    parser.add_argument('--skip-training', action='store_true',
                        help='Skip all LightGBM training horizons.')
    parser.add_argument('--skip-scoring', action='store_true',
                        help='Skip LightGBM scoring.')
    parser.add_argument('--rerun-scoring', action='store_true',
                        help='Re-score all prediction-eligible events.')
    parser.add_argument('--pit-limit', type=int, default=None,
                        help='Optional PIT event limit per PIT pass.')
    parser.add_argument('--ai-limit', type=int, default=None,
                        help='Optional AI event limit.')
    parser.add_argument('--ai-sleep', type=float, default=0.0,
                        help='Seconds between AI events.')
    parser.add_argument('--feature-limit', type=int, default=None,
                        help='Optional feature-builder event limit.')
    parser.add_argument('--start-id', type=int, default=None,
                        help='Minimum news_id for PIT and AI.')
    parser.add_argument('--end-id', type=int, default=None,
                        help='Maximum news_id for PIT and AI.')
    parser.add_argument('--pause', type=float, default=3.0,
                        help='Seconds between successful steps.')
    parser.add_argument(
        '--unmapped-only',
        action='store_true',
        help='Run exact-ID features and scoring for eligible events with no existing predictions. Does not process unresolved mappings.',
        )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='With --unmapped-only, list the target count and IDs without building features or scoring.',
        )
    return parser.parse_args()


def print_header(title: str) -> None:
    print()
    print('=' * 82)
    print(title)
    print('=' * 82)


def check_scripts(args: argparse.Namespace) -> None:
    print_header('PRE-FLIGHT CHECK')
    required = [MAPPING_ENGINE_SCRIPT, MAPPING_AGENT_SCRIPT, PIT_SCRIPT, AI_SCRIPT, FEATURE_SCRIPT, TRAIN_SCRIPT, SCORE_SCRIPT]
    missing = []
    for path in required:
        if path.exists():
            print(f'OK   {path}')
        else:
            print(f'MISS {path}')
            missing.append(path)
    if missing:
        raise RuntimeError('One or more canonical pipeline scripts are missing.')
    if args.mapping_limit is not None and args.mapping_limit <= 0:
        raise ValueError('--mapping-limit must be greater than 0.')
    if args.agent_limit is not None and args.agent_limit <= 0:
        raise ValueError('--agent-limit must be greater than 0.')
    if args.max_candidates <= 0:
        raise ValueError('--max-candidates must be greater than 0.')
    if args.max_agent_steps <= 0:
        raise ValueError('--max-agent-steps must be greater than 0.')
    if args.pit_limit is not None and args.pit_limit <= 0:
        raise ValueError('--pit-limit must be greater than 0.')
    if args.ai_limit is not None and args.ai_limit <= 0:
        raise ValueError('--ai-limit must be greater than 0.')
    if args.ai_sleep < 0:
        raise ValueError('--ai-sleep cannot be negative.')
    if args.feature_limit is not None and args.feature_limit <= 0:
        raise ValueError('--feature-limit must be greater than 0.')
    if args.start_id is not None and args.end_id is not None and args.start_id > args.end_id:
        raise ValueError('--start-id cannot be greater than --end-id.')
    if args.pause < 0:
        raise ValueError('--pause cannot be negative.')
    print()
    print(f'Project root : {PROJECT_ROOT}')
    print(f'Python       : {sys.executable}')
    print('Pre-flight   : PASS')


def run_step(step_number: int, title: str, command: list[str]) -> None:
    print_header(f'STEP {step_number} - {title}')
    print('Command:')
    print('  ' + ' '.join(f'"{item}"' if ' ' in item else item for item in command))
    print()
    started = time.time()

    # Make the project src directory importable for canonical subprocesses.
    env = os.environ.copy()
    src_dir = PROJECT_ROOT / "src"
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = str(src_dir)

    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    elapsed = time.time() - started
    print()
    print('-' * 82)
    print(f"STEP {step_number} RESULT: {'SUCCESS' if result.returncode == 0 else 'FAILED'}")
    print(f'Elapsed: {elapsed:.1f} seconds')
    print('-' * 82)
    if result.returncode != 0:
        raise RuntimeError(
            f'Step {step_number} failed with exit code {result.returncode}. Pipeline stopped.'
        )


def pause_between_steps(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def scoped_command(script: Path, *, limit: int | None = None,
                   start_id: int | None = None, end_id: int | None = None) -> list[str]:
    command = [sys.executable, str(script)]
    if limit is not None:
        command.extend(['--limit', str(limit)])
    if start_id is not None:
        command.extend(['--start-id', str(start_id)])
    if end_id is not None:
        command.extend(['--end-id', str(end_id)])
    return command


def run_mapping_engine(step: int, args: argparse.Namespace) -> None:
    command = [sys.executable, str(MAPPING_ENGINE_SCRIPT), '--init', '--persist-candidates',
               '--max-candidates', str(args.max_candidates)]
    if args.mapping_limit is None:
        command.append('--all-groups')
    else:
        command.extend(['--limit-groups', str(args.mapping_limit)])
    run_step(step, 'DETERMINISTIC MAPPING / CANDIDATE GENERATION V2.2', command)


def run_mapping_agent(step: int, args: argparse.Namespace) -> None:
    command = [sys.executable, str(MAPPING_AGENT_SCRIPT),
               '--max-candidates', str(args.max_candidates),
               '--max-agent-steps', str(args.max_agent_steps)]
    if args.agent_limit is None:
        command.append('--all-groups')
    else:
        command.extend(['--limit-groups', str(args.agent_limit)])
    run_step(step, 'MAPPING AGENT V2.0.2', command)


def run_pit(step: int, title: str, args: argparse.Namespace) -> None:
    command = scoped_command(PIT_SCRIPT, limit=args.pit_limit,
                            start_id=args.start_id, end_id=args.end_id)
    if args.pit_limit is None and args.start_id is None and args.end_id is None:
        command.append('--all')
    run_step(step, title, command)


def run_ai(step: int, args: argparse.Namespace) -> None:
    command = scoped_command(AI_SCRIPT, limit=args.ai_limit,
                            start_id=args.start_id, end_id=args.end_id)
    if args.ai_sleep:
        command.extend(['--sleep', str(args.ai_sleep)])
    run_step(step, 'AI PREDICTION - ALL FEED EVENTS', command)


def run_features(step: int, args: argparse.Namespace) -> None:
    command = [sys.executable, str(FEATURE_SCRIPT), '--new']
    if args.feature_limit is not None:
        command.extend(['--limit', str(args.feature_limit)])
    run_step(step, 'BUILD / UPDATE EVENT FEATURES', command)


def run_training(step: int, horizon: int) -> None:
    run_step(step, f'TRAIN LIGHTGBM +{horizon}D',
             [sys.executable, str(TRAIN_SCRIPT), '--horizon', str(horizon)])


def run_scoring(step: int, args: argparse.Namespace) -> None:
    command = [sys.executable, str(SCORE_SCRIPT), '--all']
    mode = 'INCREMENTAL SCORE'
    if args.rerun_scoring:
        command.append('--rerun-all')
        mode = 'FULL RE-SCORE'
    run_step(step, f'LIGHTGBM SCORING - {mode}', command)

def run_unmapped_only(args: argparse.Namespace) -> int:
    """
    Target eligible feature rows that have no LightGBM predictions yet.
    The legacy flag name is retained, but unresolved/unmapped events are
    deliberately excluded from scoring.
    """
    if args.dry_run and not args.unmapped_only:
        raise ValueError('--dry-run can only be used with --unmapped-only.')
    if args.rerun_scoring:
        raise ValueError('--rerun-scoring cannot be combined with --unmapped-only.')
    if args.skip_features or args.skip_scoring:
        raise ValueError('--unmapped-only requires feature building and scoring; remove --skip-features/--skip-scoring.')

    load_dotenv(PROJECT_ROOT / '.env')
    db_config = {
        'host': os.getenv('MARKETPULSE_DB_HOST', 'localhost'),
        'port': int(os.getenv('MARKETPULSE_DB_PORT', '5432')),
        'dbname': os.getenv('MARKETPULSE_DB_NAME', 'marketpulse'),
        'user': os.getenv('MARKETPULSE_DB_USER', 'postgres'),
        'password': os.getenv('MARKETPULSE_DB_PASSWORD', ''),
    }

    target_sql = """
        SELECT DISTINCT f.news_id
        FROM market_news_ml_features f
        WHERE f.event_trade_date IS NOT NULL
          AND f.prediction_eligible = TRUE
          AND NOT EXISTS (
              SELECT 1
              FROM market_news_ml_predictions p
              WHERE p.news_id = f.news_id
                AND p.horizon IN (1, 5, 10)
          )
        ORDER BY f.news_id;
    """

    print_header('TARGET SELECTION - ELIGIBLE EVENTS WITHOUT PREDICTIONS')
    with psycopg.connect(**db_config) as conn:
        with conn.cursor() as cur:
            cur.execute(target_sql)
            news_ids = [int(row[0]) for row in cur.fetchall()]

    print(f'Target event count: {len(news_ids):,}')
    if not news_ids:
        print('No eligible unscored feature rows found. Nothing to process.')
        return 0

    print(f'First news_id     : {news_ids[0]}')
    print(f'Last news_id      : {news_ids[-1]}')

    if args.dry_run:
        print('DRY RUN: no feature build or scoring was started.')
        print('Sample IDs       : ' + ', '.join(map(str, news_ids[:25])))
        return 0

    # Keep the exact target list in a temporary file shared by both scripts.
    with tempfile.NamedTemporaryFile(
        mode='w',
        encoding='utf-8',
        suffix='.txt',
        prefix='marketpulse_news_ids_',
        delete=False,
    ) as id_file:
        id_file.write('\\n'.join(map(str, news_ids)) + '\\n')
        ids_path = Path(id_file.name)

    try:
        run_step(
            1,
            'EXACT-ID EVENT FEATURE BUILD',
            [sys.executable, str(FEATURE_SCRIPT), '--news-ids-file', str(ids_path)],
        )
        pause_between_steps(args.pause)

        run_step(
            2,
            'EXACT-ID LIGHTGBM SCORING',
            [sys.executable, str(SCORE_SCRIPT), '--news-ids-file', str(ids_path)],
        )
        pause_between_steps(args.pause)

        run_final_audit(3)
    finally:
        try:
            ids_path.unlink(missing_ok=True)
        except OSError as exc:
            print(f'Warning: could not remove temporary ID file {ids_path}: {exc}')

    print_header('TARGETED MARKETPULSE RUN COMPLETED')
    print(f'Processed target IDs: {len(news_ids):,}')
    print('Full PIT rebuild, mapping, AI-wide processing, and model training were not run.')
    return 0


def run_final_audit(step: int) -> None:
    print_header(f'STEP {step} - FINAL DATABASE COVERAGE AUDIT')
    audit_script = '''
import os
import sys
import psycopg
from dotenv import load_dotenv
load_dotenv()
config = {
    'host': os.getenv('MARKETPULSE_DB_HOST', 'localhost'),
    'port': int(os.getenv('MARKETPULSE_DB_PORT', '5432')),
    'dbname': os.getenv('MARKETPULSE_DB_NAME', 'marketpulse'),
    'user': os.getenv('MARKETPULSE_DB_USER', 'postgres'),
    'password': os.getenv('MARKETPULSE_DB_PASSWORD', ''),
}
queries = [
    ('market_news', 'SELECT COUNT(*) FROM market_news;'),
    ('ai_prediction_events', 'SELECT COUNT(DISTINCT news_id) FROM market_news_ai_predictions;'),
    ('pit_sample_events', 'SELECT COUNT(DISTINCT news_id) FROM market_news_ml_samples;'),
    ('feature_events', 'SELECT COUNT(DISTINCT news_id) FROM market_news_ml_features;'),
    ('ml_prediction_events', 'SELECT COUNT(DISTINCT news_id) FROM market_news_ml_predictions;'),
    ('eligible_unscored', "SELECT COUNT(*) FROM market_news_ml_features f WHERE f.event_trade_date IS NOT NULL AND f.prediction_eligible = TRUE AND NOT EXISTS (SELECT 1 FROM market_news_ml_predictions p WHERE p.news_id = f.news_id AND p.horizon IN (1, 5, 10));"),
]
with psycopg.connect(**config) as conn:
    with conn.cursor() as cur:
        for name, sql in queries:
            cur.execute(sql)
            print(f'{name}: {cur.fetchone()[0]:,}')
        cur.execute('SELECT horizon, COUNT(*) FROM market_news_ml_predictions GROUP BY horizon ORDER BY horizon;')
        print('prediction_rows_by_horizon:')
        for horizon, count in cur.fetchall():
            print(f'  horizon={horizon} rows={count:,}')
print('Audit completed.')
'''
    started = time.time()

    env = os.environ.copy()
    src_dir = PROJECT_ROOT / "src"
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = str(src_dir)

    result = subprocess.run(
        [sys.executable, '-c', audit_script],
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    elapsed = time.time() - started
    print()
    print('-' * 82)
    print(f"STEP {step} RESULT: {'SUCCESS' if result.returncode == 0 else 'FAILED'}")
    print(f'Elapsed: {elapsed:.1f} seconds')
    print('-' * 82)
    if result.returncode != 0:
        raise RuntimeError('Final database audit failed. Pipeline stopped.')


def main() -> int:
    args = parse_args()
    print_header('MARKETPULSE - COMPLETE AI + PIT + LIGHTGBM PIPELINE')
    print('Pipeline starts from the PIT builder.')
    print('AI prediction is included for all feed events.')
    print('PIT is refreshed after AI so AI event fields reach ML features.')
    print('The runner stops on the first required-step failure.')
    print()
    print(f'Project: {PROJECT_ROOT}')
    check_scripts(args)

    if args.unmapped_only:
        return run_unmapped_only(args)

    step = 1

    if args.skip_mapping:
        print_header(f'STEPS {step}-{step + 1} - MAPPING SKIPPED')
        print('Skipped by --skip-mapping.')
        step += 2
    else:
        run_mapping_engine(step, args)
        step += 1
        pause_between_steps(args.pause)

        if args.skip_agent:
            print_header(f'STEP {step} - MAPPING AGENT SKIPPED')
            print('Skipped by --skip-agent.')
        else:
            run_mapping_agent(step, args)
        step += 1
        pause_between_steps(args.pause)

    run_pit(step, 'BUILD PIT ML DATASET', args)
    step += 1
    pause_between_steps(args.pause)

    if args.skip_ai:
        print_header(f'STEP {step} - AI PREDICTION SKIPPED')
        print('Skipped by --skip-ai.')
    else:
        run_ai(step, args)
    step += 1
    pause_between_steps(args.pause)

    if args.skip_ai or args.skip_pit_refresh:
        print_header(f'STEP {step} - PIT REFRESH SKIPPED')
        print('Skipped because AI was skipped or --skip-pit-refresh was supplied.')
    else:
        run_pit(step, 'REFRESH PIT DATASET AFTER AI PREDICTION', args)
    step += 1
    pause_between_steps(args.pause)

    if args.skip_features:
        print_header(f'STEP {step} - EVENT FEATURES SKIPPED')
        print('Skipped by --skip-features.')
    else:
        run_features(step, args)
    step += 1
    pause_between_steps(args.pause)

    if args.skip_training:
        print_header(f'STEPS {step}-{step + 2} - TRAINING SKIPPED')
        print('All LightGBM training horizons skipped by --skip-training.')
        step += 3
    else:
        for horizon in (1, 5, 10):
            run_training(step, horizon)
            step += 1
            pause_between_steps(args.pause)

    if args.skip_scoring:
        print_header(f'STEP {step} - LIGHTGBM SCORING SKIPPED')
        print('Skipped by --skip-scoring.')
    else:
        run_scoring(step, args)
    step += 1
    pause_between_steps(args.pause)

    run_final_audit(step)

    print_header('MARKETPULSE PIPELINE COMPLETED')
    print('1. Deterministic mapping candidate generation V2.2')
    print('2. Mapping Agent V2.0.2')
    print('3. PIT ML dataset')
    print('4. AI prediction for all unpredicted feed events')
    print('5. PIT refresh after AI')
    print('6. Event-level features')
    print('7. LightGBM +1D training')
    print('8. LightGBM +5D training')
    print('9. LightGBM +10D training')
    print('10. LightGBM +1D/+5D/+10D scoring')
    print('11. Read-only database coverage audit')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        print('=' * 82)
        print('PIPELINE INTERRUPTED')
        print('=' * 82)
        raise SystemExit(130)
    except Exception as exc:
        print()
        print('=' * 82)
        print('PIPELINE STOPPED')
        print('=' * 82)
        print(str(exc))
        raise SystemExit(1)
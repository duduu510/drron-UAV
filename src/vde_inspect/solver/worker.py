"""Isolated simulation process. Stdout is bounded JSONL protocol, never UI work."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback

from vde_inspect.solver.baseline import normalize_config, solve_baseline
from vde_inspect.solver.baseline_validator import validate_baseline_solution


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)

    def emit(message):
        print(json.dumps(message, ensure_ascii=True, allow_nan=False), flush=True)

    try:
        if args.output.exists():
            raise FileExistsError('结果文件已存在，不可覆盖历史运行')
        request = json.loads(args.request.read_text(encoding='utf-8'))
        config = normalize_config(request['config'])
        solution = solve_baseline(request['project'], config, run_id=request['run_id'],
                                  solution_id=request['solution_id'], progress=emit)
        solution['baseline_validation'] = validate_baseline_solution(solution, request['project'], config)
        # This checker proves only the declared simulation model, never operational safety.
        solution['validation_passed'] = False
        solution['publishable'] = False
        temporary = args.output.with_suffix('.tmp')
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(solution, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(args.output)
        emit({'type': 'summary', 'run_id': solution['run_id'],
              'complete': solution['complete'], 'baseline_passed': solution['baseline_validation']['passed']})
        return 0
    except Exception as exc:
        emit({'type': 'error', 'message': str(exc)})
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Qt process owner for durable, cancellable simulation runs."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from vde_inspect.solver.adapter import load_fixture


class BaselineRunManager(QObject):
    progress = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()
    log = Signal(str)
    MAX_LINE = 256 * 1024

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._running = False
        self._cancel_requested = False
        self._buffer = b''
        self._directory = None
        self._request = None
        self._error = ''
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._kill)

    @property
    def running(self):
        return self._running

    def _state(self, status, **extra):
        payload = {'status': status, 'run_id': self._request['run_id'],
                   'updated_at': datetime.now(timezone.utc).isoformat(), **extra}
        target = self._directory / 'state.json'
        temporary = self._directory / 'state.tmp'
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)

    def start(self, project, config, run_directory):
        if self.running:
            raise RuntimeError('仿真任务已在运行')
        directory = Path(run_directory).resolve()
        if directory.exists() and any(directory.iterdir()):
            raise FileExistsError('运行目录必须为空，历史运行不可覆盖')
        # Serialize first: detach mutable UI objects and reject unsupported JSON.
        request = json.loads(json.dumps({'project': project, 'config': config,
                                        'run_id': str(uuid4()), 'solution_id': str(uuid4())}, allow_nan=False))
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / 'request.json').open('x', encoding='utf-8') as stream:
            json.dump(request, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        (directory / 'events.jsonl').touch(exist_ok=False)
        (directory / 'stderr.log').touch(exist_ok=False)
        self._directory, self._request = directory, request
        self._buffer, self._error = b'', ''
        self._running, self._cancel_requested = True, False
        process = QProcess(self)
        self._process = process
        environment = QProcessEnvironment.systemEnvironment()
        source_root = str(Path(__file__).resolve().parents[2])
        inherited_pythonpath = environment.value('PYTHONPATH')
        environment.insert('PYTHONPATH', source_root + (os.pathsep + inherited_pythonpath if inherited_pythonpath else ''))
        process.setProcessEnvironment(environment)
        process.setWorkingDirectory(str(Path(__file__).resolve().parents[3]))
        # Editable installs need no special environment; preserve explicit PYTHONPATH too.
        process.readyReadStandardOutput.connect(self._stdout)
        process.readyReadStandardError.connect(self._stderr)
        process.finished.connect(self._done)
        process.errorOccurred.connect(self._process_error)
        self._state('running')
        process.start(sys.executable, ['-m', 'vde_inspect.solver.worker', '--request',
                                      str(directory / 'request.json'), '--output', str(directory / 'result.json')])

    def _record(self, data):
        with (self._directory / 'events.jsonl').open('ab') as stream:
            stream.write(data + b'\n')

    def _line(self, line):
        self._record(line)
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError('worker message must be an object')
            if message.get('type') == 'progress':
                counts = [message.get(key) for key in ('processed', 'total', 'completed')]
                if any(type(value) is not int or value < 0 for value in counts) or not counts[2] <= counts[0] <= counts[1]:
                    raise ValueError('invalid worker progress counters')
                self.progress.emit(message)
            elif message.get('type') == 'error':
                self._error = str(message.get('message', 'worker error'))
            self.log.emit(str(message.get('message', line.decode('utf-8', errors='replace'))))
        except (ValueError, UnicodeError) as exc:
            self._error = f'无效子进程协议: {exc}'
            self._process.kill()

    def _stdout(self):
        self._buffer += bytes(self._process.readAllStandardOutput())
        while b'\n' in self._buffer:
            line, self._buffer = self._buffer.split(b'\n', 1)
            if len(line) > self.MAX_LINE:
                self._error = '子进程消息超过大小限制'
                self._process.kill()
                self._buffer = b''
                return
            if line.strip():
                self._line(line)
        if len(self._buffer) > self.MAX_LINE:
            self._error = '子进程消息超过大小限制'
            self._buffer = b''
            self._process.kill()

    def _stderr(self):
        data = bytes(self._process.readAllStandardError())
        with (self._directory / 'stderr.log').open('ab') as stream:
            stream.write(data)
        if data:
            self.log.emit(data[:8192].decode('utf-8', errors='replace'))

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._error = self._process.errorString()
            self._done(-1, QProcess.ExitStatus.CrashExit)

    def _done(self, exit_code, exit_status):
        if not self.running:
            return
        self._kill_timer.stop()
        self._stdout()
        self._stderr()
        if self._buffer.strip():
            self._line(self._buffer)
        self._buffer = b''
        self._running = False
        process = self._process
        self._process = None
        process.deleteLater()
        if self._cancel_requested:
            self._state('cancelled', exit_code=exit_code)
            self.cancelled.emit()
            return
        try:
            if self._error or exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
                raise ValueError(self._error or f'仿真子进程退出: {exit_code}')
            result = load_fixture(self._directory / 'result.json')
            for key in ('run_id', 'solution_id'):
                if result[key] != self._request[key]:
                    raise ValueError(f'结果 {key} 与冻结请求不匹配')
            for key in ('project_id', 'input_hash'):
                if result[key] != self._request['project'][key]:
                    raise ValueError(f'结果 {key} 与冻结输入不匹配')
            report = result.get('baseline_validation')
            if (result.get('source_mode') != 'simulation' or result.get('publishable') is not False or
                    result.get('validation_passed') is not False or not isinstance(report, dict) or
                    type(result.get('complete')) is not bool or type(report.get('passed')) is not bool or
                    report.get('publishable') is not False or not isinstance(report.get('checks'), list) or
                    not isinstance(report.get('violations'), list) or report.get('scope') != 'simulation-baseline'):
                raise ValueError('结果缺少有效的仿真校验报告')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self._state('failed', exit_code=exit_code, error=str(exc))
            self.failed.emit(str(exc))
            return
        result['provenance_label'] = '本机新计算的仿真基线（研究模型）'
        self._state('finished', exit_code=exit_code, complete=result['complete'])
        self.finished.emit(result)

    def cancel(self):
        if not self.running or self._cancel_requested:
            return
        self._cancel_requested = True
        self._state('cancelling')
        self._process.terminate()
        self._kill_timer.start(1500)

    def _kill(self):
        if self.running and self._process:
            self._process.kill()

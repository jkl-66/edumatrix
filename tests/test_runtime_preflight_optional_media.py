from pathlib import Path
import sys
from types import SimpleNamespace

from scripts import runtime_preflight


def test_unavailable_optional_media_does_not_block_core_startup(monkeypatch, capsys):
    monkeypatch.setattr(runtime_preflight, 'EXPECTED_PREFIX', Path(sys.executable).resolve().parent)

    def dependency(name):
        if name.startswith('app.'):
            return SimpleNamespace(runtime_status=lambda: {'available': False, 'failure_code': 'synthetic_missing_runtime'})
        return SimpleNamespace(__version__='test-version')

    monkeypatch.setattr(runtime_preflight, 'import_module', dependency)
    assert runtime_preflight.main() == 0
    output = capsys.readouterr().out
    assert '[WARN] Optional whisper.cpp runtime unavailable' in output
    assert '[WARN] Optional FFmpeg runtime unavailable' in output
    assert 'Runtime preflight: PASS' in output


def test_broken_optional_runtime_is_reported_and_does_not_hide_other_checks(monkeypatch, capsys):
    checked = []

    def dependency(name):
        checked.append(name)
        if name == 'app.offline_speech':
            raise ImportError('synthetic optional failure')
        return SimpleNamespace(runtime_status=lambda: {'available': True, 'ffmpeg_version': 'test-ffmpeg'})

    monkeypatch.setattr(runtime_preflight, 'import_module', dependency)
    runtime_preflight.check_optional_media()
    assert checked == ['app.offline_speech', 'app.video_rendering']
    output = capsys.readouterr().out
    assert 'Optional whisper.cpp runtime check failed' in output
    assert 'test-ffmpeg' in output


def test_missing_core_dependency_still_blocks_startup(monkeypatch, capsys):
    monkeypatch.setattr(runtime_preflight, 'EXPECTED_PREFIX', Path(sys.executable).resolve().parent)

    def dependency(name):
        if name == 'pandas':
            raise ImportError('synthetic missing core dependency')
        return SimpleNamespace(__version__='test-version')

    monkeypatch.setattr(runtime_preflight, 'import_module', dependency)
    assert runtime_preflight.main() == 1
    output = capsys.readouterr().out
    assert 'Missing or broken dependency pandas' in output
    assert 'Runtime preflight: PASS' not in output

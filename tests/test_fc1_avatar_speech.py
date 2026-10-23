from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_local_avatar_speech_is_reachable_from_speech_workspace():
    workspace = (ROOT / "frontend/src/views/SpeechTraining.vue").read_text(encoding="utf-8")
    avatar = (ROOT / "frontend/src/components/AvatarSpeech.vue").read_text(encoding="utf-8")

    assert "import AvatarSpeech from '../components/AvatarSpeech.vue'" in workspace
    assert 'data-testid="local-avatar-speech"' in workspace
    assert '<AvatarSpeech :text="displayText" />' in workspace
    assert "speechSynthesis" in avatar
    assert "defineExpose" in avatar
    assert "文本" in workspace

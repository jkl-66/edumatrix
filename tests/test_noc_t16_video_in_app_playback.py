from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIDEO_WORKSPACE = ROOT / "frontend/src/views/VideoRecommendationWorkspace.vue"
RESOURCE_CENTER = ROOT / "frontend/src/views/ResourceCenter.vue"


def test_video_workspace_keeps_playback_inside_edumatrix():
    source = VIDEO_WORKSPACE.read_text(encoding="utf-8")

    assert '<video' in source
    assert 'data-testid="video-player"' in source
    assert '<iframe' in source
    assert 'data-testid="embedded-video-player"' in source
    assert 'allow="autoplay; encrypted-media; picture-in-picture"' in source
    assert 'sandbox="allow-scripts allow-same-origin allow-forms allow-presentation"' in source
    assert 'openInAppSource' in source
    assert 'window.open' not in source
    assert 'target="_blank"' not in source
    assert '站内嵌入' in source
    assert '该来源暂不允许站内嵌入' in source


def test_video_workspace_adapts_known_provider_urls_to_embed_players():
    source = VIDEO_WORKSPACE.read_text(encoding="utf-8")

    assert 'player.bilibili.com/player.html?bvid=' in source
    assert 'player.bilibili.com/player.html?aid=' in source
    assert 'www.youtube.com/embed/' in source
    assert 'v.qq.com/txp/iframe/player.html?vid=' in source
    assert 'player.youku.com/embed/' in source
    assert '普通 HTTPS 视频页也留在当前工作区内加载' in source


def test_resource_center_still_uses_the_dedicated_video_workspace_route():
    center = RESOURCE_CENTER.read_text(encoding="utf-8")
    router = (ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8")

    assert "{ id: 'video', label: '视频推荐'" in center
    assert "name: 'VideoResource', component: VideoRecommendationWorkspace" in router
    assert "getM5VideoMedia" in VIDEO_WORKSPACE.read_text(encoding="utf-8")

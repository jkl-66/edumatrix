from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "frontend" / "src" / "views" / "MarketplaceWorkspace.vue"
BUNDLE = ROOT / "frontend" / "src" / "views" / "ResourceBundleWorkspace.vue"
PATH = ROOT / "frontend" / "src" / "views" / "LearningPathGraph.vue"
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"
APP = ROOT / "frontend" / "src" / "App.vue"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_discovery_is_a_lightweight_74_26_market_with_selected_preview() -> None:
    market = source(MARKET)

    for marker in (
        'data-testid="marketplace-workspace"',
        'class="filter-bar"',
        'class="market-layout"',
        'data-testid="marketplace-preview"',
        "grid-template-columns:minmax(0,74fr) minmax(300px,26fr)",
        "搜索标题、知识点或标签",
        "全部分类",
        "单份资源",
        "资源包",
        "学习路径",
        "选择一份内容查看概览",
        "包含内容",
        "来源与许可",
    ):
        assert marker in market

    assert "getMarketplaceListing" in market
    assert "selected.value = await getMarketplaceListing" in market
    for forbidden in ("责任记录", "举报处置", "组织市场", "市场定价", "三方差异"):
        assert forbidden not in market


def test_publication_is_three_steps_and_switches_personal_object_type() -> None:
    market = source(MARKET)

    assert 'data-testid="marketplace-publish-wizard"' in market
    assert "v-for=\"step in 3\"" in market
    assert "['选择类型', '选择内容并说明', '确认并提交']" in market
    assert "['resource', 'resource_bundle', 'learning_path']" in market
    assert "workspace.value?.publishable_sources?.[draft.value.item_type]" in market
    assert "draft.value.source_object_id = ''" in market
    assert "draft.value.title = ''" not in market
    assert "draft.value.summary = ''" not in market
    assert "!provenance.value?.complete" in market
    assert "来源或许可信息不完整，暂时不能公开发布" in market
    assert ":disabled=\"Boolean(busy) || !provenance?.complete\"" in market
    assert "提交失败，已填写内容仍然保留" in market


def test_preview_actions_keep_one_primary_action_and_preserve_loaded_content() -> None:
    market = source(MARKET)

    assert ':class="{ secondary: !isDiscover || selected }"' in market
    assert "v-else-if=\"detailError && !selected\"" in market
    assert "v-else-if=\"selected\" class=\"preview-content\"" in market
    assert "v-if=\"detailError\" class=\"inline-error\"" in market
    assert "保存失败，当前预览和选择不会丢失" in market
    assert "收藏状态更新失败" in market
    assert "selected.value = null" not in market[market.index("async function saveCopy"):market.index("async function toggleFavorite")]
    assert "selected.value = null" not in market[market.index("async function toggleFavorite"):market.index("function choosePublishType")]
    assert market.count('class="primary-button"') >= 5
    assert 'class="icon-button" :title="selected.engagement?.is_favorited' in market


def test_source_license_demo_and_personal_copy_states_are_visible() -> None:
    market = source(MARKET)

    for marker in (
        "source_label",
        "license_label",
        "is_demo_data",
        "demo_label",
        "已加入个人空间",
        "打开个人副本",
        "来源已下架，个人副本仍可继续使用",
        "个人副本独立保存，上游更新或下架不会覆盖你的内容",
    ):
        assert marker in market

    assert "selectedSavedCopy.open_route" in market
    assert "personalCopies" in market
    assert "mineTab === 'copies'" in market


def test_personal_copy_routes_open_real_bundle_and_owned_learning_path() -> None:
    bundle = source(BUNDLE)
    path = source(PATH)

    assert "route.query.mode === 'personal-copy'" in bundle
    assert "? adaptPersonalBundle(await getResourceBundle(bundleId))" in bundle
    assert ": await getGenerationJob(bundleId)" in bundle
    assert "v-else-if=\"item.state === 'failed' && !isPersonalCopy\"" in bundle
    assert "router.push('/marketplace/mine')" in bundle
    assert "个人副本独立保存，上游变化不会覆盖当前内容" in bundle

    assert "String(route.query.path_id || '')" in path
    assert "const isPersonalPath = computed(() => Boolean(route.query.path_id))" in path
    assert "isPersonalPath.value ? Promise.resolve(null)" in path
    assert "isLearner.value && !isPersonalPath.value && courseId" in path
    assert 'v-if="isLearner && !isPersonalPath"' in path
    assert 'v-if="!isPersonalPath" type="button" class="path-secondary-action"' in path
    assert "m5Paths.value.find(item => String(item.id) === requestedPathId)" in path
    assert "这条个人学习路径不存在或不属于当前账号" in path
    assert "m5Path.value = requestedPath" in path
    assert "|| pathRecords.value.find(item => item.course_id === courseId)" in path
    assert 'data-testid="path-error"' in path
    assert "学习路径暂时无法打开" in path


def test_marketplace_deep_links_stay_in_one_of_eight_student_spaces() -> None:
    router = source(ROUTER)
    app = source(APP)

    for route_contract in (
        "path: '/marketplace', name: 'Marketplace'",
        "path: '/marketplace/items/:itemId', name: 'MarketplaceItem'",
        "path: '/marketplace/publish', name: 'MarketplacePublish'",
        "path: '/marketplace/mine', name: 'MarketplaceMine'",
    ):
        assert route_contract in router
    assert router.count("component: MarketplaceWorkspace") >= 4
    assert "targetMeta('学习市场', '资源发现', STUDENT, { navigationLevel: 'primary' })" in router
    assert "targetMeta('学习资源详情', '学习市场', STUDENT)" in router
    assert "targetMeta('发布学习内容', '学习市场', STUDENT)" in router
    assert "targetMeta('我的分享与收藏', '学习市场', STUDENT)" in router

    match = re.search(r"const studentNav = \[(.*?)\n\]", app, flags=re.DOTALL)
    assert match
    entries = re.findall(r"\{ path: '([^']+)', label: '([^']+)', icon: \w+ \}", match.group(1))
    assert entries == [
        ("/", "首页"),
        ("/profile", "个人中心"),
        ("/profile/learning", "学习画像"),
        ("/workspace", "学习空间"),
        ("/learn", "智能对话"),
        ("/knowledge", "知识库"),
        ("/marketplace", "学习市场"),
        ("/settings", "设置"),
    ]


def test_marketplace_keeps_the_frozen_light_desktop_visual_contract() -> None:
    market = source(MARKET).lower()

    for required in (
        "var(--color-surface)",
        "var(--color-text)",
        "var(--color-accent)",
        "var(--color-border)",
        "border-radius:var(--radius-panel)",
        "border-radius:var(--radius-control)",
    ):
        assert required in market
    assert "font-family:var(--font-heading)" in market

    numeric_font_sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", market)]
    assert numeric_font_sizes
    assert min(numeric_font_sizes) >= 14

    numeric_radii = [int(value) for value in re.findall(r"border-radius:\s*(\d+)px", market)]
    assert numeric_radii
    assert max(numeric_radii) <= 8

    for forbidden in (
        "linear-gradient",
        "radial-gradient",
        "backdrop-filter",
        "#10b981",
        "#22c55e",
        "#16a34a",
        "#0ea5e9",
        "#3b82f6",
        "#8b5cf6",
        "#a855f7",
        "#92400e",
        "#b45309",
        "#a16207",
        "green-",
        "emerald-",
        "lime-",
        "orange-",
        "amber-",
        "purple-",
        "indigo-",
    ):
        assert forbidden not in market

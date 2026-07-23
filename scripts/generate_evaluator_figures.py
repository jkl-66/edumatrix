"""Generate evaluator-facing technical diagrams for the EduMatrix documents."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "figures"
OUTPUT.mkdir(parents=True, exist_ok=True)

BG = "#F7FAF8"
INK = "#20352D"
MUTED = "#64756D"
GREEN = "#2F6B57"
GREEN_LIGHT = "#DDEEE6"
BLUE = "#3B6EA5"
BLUE_LIGHT = "#DFECF8"
AMBER = "#B97924"
AMBER_LIGHT = "#FFF0D5"
RED = "#B84E4E"
RED_LIGHT = "#F9E2E2"
PURPLE = "#6B5B95"
PURPLE_LIGHT = "#ECE7F7"
WHITE = "#FFFFFF"


def pick_font(size: int, bold: bool = False):
    candidates = (
        [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\Noto Sans SC Bold (TrueType).otf"]
        if bold
        else [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\Noto Sans SC (TrueType).otf"]
    )
    candidates += [r"C:\Windows\Fonts\Deng.ttf", r"C:\Windows\Fonts\simhei.ttf"]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and text_width(draw, candidate, font) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def write_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill=INK, max_width: int | None = None, spacing: int = 8, anchor: str | None = None):
    if max_width:
        lines = wrap_text(draw, text, font, max_width)
        draw.multiline_text(xy, "\n".join(lines), font=font, fill=fill, spacing=spacing, anchor=anchor)
    else:
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def base(title: str, subtitle: str, size=(1600, 980)):
    image = Image.new("RGB", size, BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0], 18), fill=GREEN)
    write_text(draw, (64, 46), title, pick_font(34, True), fill=INK)
    write_text(draw, (66, 98), subtitle, pick_font(18), fill=MUTED)
    draw.line((64, 142, size[0] - 64, 142), fill="#D7E3DC", width=2)
    draw.text((size[0] - 64, size[1] - 34), "EduMatrix 智教矩阵  |  评委技术说明图", font=pick_font(14), fill=MUTED, anchor="rs")
    return image, draw


def rounded_box(draw, xy, title: str, detail: str = "", fill=WHITE, outline="#C8D9D0", accent=GREEN, radius=18, title_size=22, detail_size=15):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=2)
    draw.rounded_rectangle((x1, y1, x1 + 8, y2), radius=4, fill=accent)
    write_text(draw, (x1 + 28, y1 + 22), title, pick_font(title_size, True), fill=INK, max_width=x2 - x1 - 48)
    if detail:
        write_text(draw, (x1 + 28, y1 + 62), detail, pick_font(detail_size), fill=MUTED, max_width=x2 - x1 - 48, spacing=6)


def arrow(draw, start: tuple[int, int], end: tuple[int, int], color=GREEN, width=4):
    draw.line((*start, *end), fill=color, width=width)
    x1, y1 = start
    x2, y2 = end
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 >= x1 else -1
        points = [(x2, y2), (x2 - 14 * direction, y2 - 8), (x2 - 14 * direction, y2 + 8)]
    else:
        direction = 1 if y2 >= y1 else -1
        points = [(x2, y2), (x2 - 8, y2 - 14 * direction), (x2 + 8, y2 - 14 * direction)]
    draw.polygon(points, fill=color)


def save(image: Image.Image, name: str):
    path = OUTPUT / name
    image.save(path, "PNG", optimize=True)
    print(path)


def architecture():
    image, draw = base("总体技术架构", "前端展示、接口编排、智能学习引擎、数据与运行时四层协同")
    bands = [
        (180, 330, "前端展示层", ["Vue 3 页面", "SSE 流式对话", "知识图谱 / 图表", "Markdown / 公式 / 资源卡片"], BLUE_LIGHT, BLUE),
        (370, 520, "FastAPI 接口层", ["认证与学生范围", "画像 / 测验 / 复习", "知识库 / RAG", "代码 / 报告 / 教师端"], GREEN_LIGHT, GREEN),
        (560, 710, "智能学习引擎", ["画像探针与 ZPD", "Hybrid RAG + DRAG", "五类资源工厂", "对齐校验与策略"], PURPLE_LIGHT, PURPLE),
        (750, 900, "数据与运行时", ["SQLite / WAL", "内存索引 / FAISS", "图谱 / 公式 / 视觉证据", "disabled / trusted_local / Docker"], AMBER_LIGHT, AMBER),
    ]
    for y1, y2, band_title, items, fill, accent in bands:
        draw.rounded_rectangle((64, y1, 1536, y2), radius=24, fill=fill, outline=accent, width=2)
        write_text(draw, (90, y1 + 20), band_title, pick_font(24, True), fill=accent)
        width = 300
        for i, item in enumerate(items):
            x = 350 + i * 285
            rounded_box(draw, (x, y1 + 22, x + width, y2 - 22), item, fill=WHITE, outline="#C8D9D0", accent=accent, title_size=19, detail_size=13)
    for y in (330, 520, 710):
        arrow(draw, (800, y + 5), (800, y + 37), GREEN)
    save(image, "01-system-architecture.png")


def learning_loop():
    image, draw = base("个性化学习闭环", "每一次学习交互都会产生新的证据，并反哺画像、路径和资源选择")
    steps = [
        (100, 230, "01 画像输入", "专业、目标、认知风格、历史"),
        (460, 230, "02 状态诊断", "弱点、掌握度、误概念、负荷"),
        (820, 230, "03 路径规划", "知识图谱、前置闭包、ZPD"),
        (1180, 230, "04 证据检索", "文本、图谱、公式、视觉、私有文档"),
        (100, 560, "05 资源生成", "讲义、导图、代码、题目、脚本"),
        (460, 560, "06 一致性校验", "引用、公式、变量、结论对齐"),
        (820, 560, "07 学习反馈", "答题、代码、追问、复习行为"),
        (1180, 560, "08 动态更新", "画像快照、路径重规划、复习计划"),
    ]
    for x, y, title, detail in steps:
        rounded_box(draw, (x, y, x + 300, y + 150), title, detail, fill=WHITE, outline="#C8D9D0", accent=GREEN, title_size=19, detail_size=14)
    arrows = [((400, 305), (460, 305)), ((760, 305), (820, 305)), ((1120, 305), (1180, 305)), ((1330, 380), (1330, 560)), ((1180, 635), (1120, 635)), ((820, 635), (760, 635)), ((460, 635), (400, 635)), ((250, 560), (250, 380))]
    for start, end in arrows:
        arrow(draw, start, end, GREEN)
    write_text(draw, (800, 465), "反馈不是日志终点，而是下一轮个性化决策的输入", pick_font(20, True), fill=GREEN, anchor="mm")
    save(image, "02-learning-loop.png")


def agent_collaboration():
    image, draw = base("多智能体协同分工", "诊断与决策、资源生成、质量验证三类角色通过统一编排器协作")
    rounded_box(draw, (70, 410, 300, 570), "学习请求", "问题 + 画像 + 历史", fill=BLUE_LIGHT, accent=BLUE, title_size=22, detail_size=15)
    rounded_box(draw, (1280, 820, 1530, 930), "资源包", "可解释、可追溯、可反馈", fill=GREEN_LIGHT, accent=GREEN, title_size=21, detail_size=13)
    groups = [
        (380, "诊断与决策", ["画像探针", "路径规划师", "教学路由"], PURPLE_LIGHT, PURPLE),
        (790, "资源生成", ["理论教授", "逻辑画师", "极客助教", "考官", "虚拟导演"], BLUE_LIGHT, BLUE),
        (1180, "验证与反馈", ["量化评估师", "证据清洗", "跨模态对齐"], AMBER_LIGHT, AMBER),
    ]
    for x, title, items, fill, accent in groups:
        draw.rounded_rectangle((x, 180, x + 330, 800), radius=24, fill=fill, outline=accent, width=2)
        write_text(draw, (x + 26, 205), title, pick_font(23, True), fill=accent)
        for i, item in enumerate(items):
            y = 290 + i * 88
            rounded_box(draw, (x + 25, y, x + 305, y + 62), item, fill=WHITE, accent=accent, title_size=18, detail_size=12)
    arrow(draw, (300, 490), (380, 490), BLUE)
    arrow(draw, (710, 490), (790, 490), PURPLE)
    arrow(draw, (1120, 490), (1180, 490), BLUE)
    arrow(draw, (1345, 800), (1400, 820), GREEN)
    write_text(draw, (800, 875), "统一输出 Agent、资源类型、引用、状态、对齐结果和反馈字段", pick_font(18, True), fill=MUTED, anchor="mm")
    save(image, "03-agent-collaboration.png")


def rag_visibility():
    image, draw = base("知识库与证据隔离", "公共课程可共享，用户文档按 owner 强制过滤，生成结果保留证据链")
    rounded_box(draw, (70, 230, 410, 410), "公共课程", "25 份 Markdown 知识点\nvisibility = public", fill=GREEN_LIGHT, accent=GREEN, title_size=23, detail_size=16)
    rounded_box(draw, (70, 540, 410, 720), "用户私有文档", "PDF / PPTX / TXT\nowner = current_user", fill=BLUE_LIGHT, accent=BLUE, title_size=23, detail_size=16)
    rounded_box(draw, (520, 370, 820, 580), "解析与分块", "文件检查\n文本 / 视觉元数据\nchunk + source", fill=WHITE, accent=AMBER, title_size=22, detail_size=15)
    rounded_box(draw, (930, 370, 1230, 580), "索引与过滤", "图谱 / 文本 / 公式\nowner_id + visibility\n检索前后双重约束", fill=PURPLE_LIGHT, accent=PURPLE, title_size=22, detail_size=15)
    rounded_box(draw, (1340, 370, 1530, 580), "生成证据", "引用 ID\n来源\n置信度", fill=GREEN_LIGHT, accent=GREEN, title_size=22, detail_size=15)
    arrow(draw, (410, 320), (520, 440), GREEN)
    arrow(draw, (410, 630), (520, 510), BLUE)
    arrow(draw, (820, 475), (930, 475), AMBER)
    arrow(draw, (1230, 475), (1340, 475), PURPLE)
    write_text(draw, (800, 830), "删除链路：数据库记录 → 上传文件 → 用户索引 → 结果复核", pick_font(19, True), fill=GREEN, anchor="mm")
    save(image, "04-rag-visibility.png")


def data_lifecycle():
    image, draw = base("数据生命周期与反馈", "学习事件进入持久化层，再形成画像快照、推荐和复习计划")
    stages = [
        (100, "身份", "用户 / JWT / 角色", BLUE, BLUE_LIGHT),
        (390, "画像", "专业 / 目标 / 掌握度", PURPLE, PURPLE_LIGHT),
        (680, "学习事件", "对话 / 答题 / 代码 / 行为", AMBER, AMBER_LIGHT),
        (970, "资源与证据", "引用 / 对齐 / 生成状态", GREEN, GREEN_LIGHT),
        (1260, "反馈计划", "路径 / 错题 / 间隔复习", RED, RED_LIGHT),
    ]
    for x, title, detail, accent, fill in stages:
        rounded_box(draw, (x, 350, x + 240, 570), title, detail, fill=fill, accent=accent, title_size=22, detail_size=15)
    for x in (340, 630, 920, 1210):
        arrow(draw, (x, 460), (x + 50, 460), GREEN)
    draw.arc((430, 610, 1120, 930), 15, 165, fill=GREEN, width=5)
    arrow(draw, (525, 700), (500, 700), GREEN)
    write_text(draw, (800, 790), "下一轮对话与路径重新读取画像快照", pick_font(20, True), fill=GREEN, anchor="mm")
    write_text(draw, (800, 220), "SQLite / WAL 作为单机验收持久化；向量索引和图谱按配置启用", pick_font(19), fill=MUTED, anchor="mm")
    save(image, "05-data-lifecycle.png")


def sandbox_modes():
    image, draw = base("代码执行模式边界", "核心学习闭环不依赖 Docker，三种模式明确区分执行能力与隔离等级")
    columns = [
        (90, "disabled", "默认提交模式", "不执行代码\n返回明确 503\n核心学习功能正常", GREEN_LIGHT, GREEN),
        (610, "trusted_local", "可信本机研究演示", "受限子进程\nAST / 超时 / 输出上限\n不具备容器隔离", AMBER_LIGHT, AMBER),
        (1130, "docker", "容器级增强路径", "无网络容器\n资源限制\n依赖 Docker daemon", BLUE_LIGHT, BLUE),
    ]
    for x, title, subtitle, detail, fill, accent in columns:
        rounded_box(draw, (x, 250, x + 380, 700), title, f"{subtitle}\n\n{detail}", fill=fill, accent=accent, title_size=28, detail_size=18)
        draw.ellipse((x + 160, 535, x + 220, 595), fill=accent)
    write_text(draw, (800, 835), "任何模式都不应被表述为绝对安全；trusted_local 仅用于可信机器，Docker 需单独验收", pick_font(19, True), fill=MUTED, anchor="mm")
    save(image, "06-sandbox-modes.png")


def main():
    architecture()
    learning_loop()
    agent_collaboration()
    rag_visibility()
    data_lifecycle()
    sandbox_modes()


if __name__ == "__main__":
    main()

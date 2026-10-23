from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from document_parser import parse_document


REPOSITORY = ROOT / "data" / "raw" / "github_repos" / "edge-impulse-courseware"
OUTPUT_DIR = ROOT / "data" / "curated" / "embedded_machine_learning_engineering_v2"
REVISION = "a3d5f9df06d0b6750d5227eb3e0359e9ffbbe1e6"
REPOSITORY_KEY = "edge-impulse-courseware"
REPOSITORY_URL = "https://github.com/edgeimpulse/courseware-embedded-machine-learning"
LICENSE_SPDX = "CC-BY-NC-SA-4.0"
COURSE_ID = "course-embedded-machine-learning-engineering-v2"

MODULES = (
    {
        "number": 1,
        "title": "边缘机器学习导论与责任边界",
        "code": "EML-KP-01",
        "level": "foundation",
        "prerequisites": [],
        "pptx": "Module 1 - Introduction to Machine Learning/1.2.1.limitations-and-ethics.1.pptx",
        "docx": "Module 1 - Introduction to Machine Learning/1.3.6.sample-tensorflow-code.3.docx",
        "engineering": [
            "把业务目标改写为可观测的传感器输入、模型输出和设备动作。",
            "区分训练环境、边缘设备和真实现场的数据分布差异。",
            "在立项阶段记录隐私、公平性、误报成本和人工接管条件。",
            "用最小可运行样例验证数据读取、推理接口和输出解释。",
        ],
        "checks": [
            "能够解释为什么低延迟、隐私和断网可用性会推动边缘推理。",
            "能够列出模型失败对用户、设备和业务流程造成的后果。",
            "能够为一个应用写出输入、输出、指标、约束和停止条件。",
        ],
    },
    {
        "number": 2,
        "title": "神经网络训练与嵌入式约束",
        "code": "EML-KP-02",
        "level": "foundation",
        "prerequisites": ["EML-KP-01"],
        "pptx": "Module 2 - Getting Started with Deep Learning/2.2.1.introduction-to-neural-networks.1.pptx",
        "docx": "Module 2 - Getting Started with Deep Learning/2.2.2.initialization-and-learning.3.docx",
        "engineering": [
            "从张量形状、参数量和激活内存三个维度估算模型成本。",
            "通过训练集、验证集和测试集分离避免把调参结果当成泛化能力。",
            "观察学习率、损失曲线和过拟合信号，而不是只看最终准确率。",
            "在模型结构确定前先明确设备 RAM、Flash、时延和功耗预算。",
        ],
        "checks": [
            "能够手工说明前向传播、损失计算、反向传播和参数更新的关系。",
            "能够判断训练不收敛、欠拟合和过拟合对应的不同处理方式。",
            "能够比较更深网络与更小网络在精度和部署成本上的取舍。",
        ],
    },
    {
        "number": 3,
        "title": "端到端机器学习工程工作流",
        "code": "EML-KP-03",
        "level": "core",
        "prerequisites": ["EML-KP-01", "EML-KP-02"],
        "pptx": "Module 3 - Machine Learning Workflow/3.3.5.how-to-evaluate-a-model.1.pptx",
        "docx": "Module 3 - Machine Learning Workflow/3.1.4.machine-learning-lifecycle.3.docx",
        "engineering": [
            "建立采集、标注、切分、特征、训练、评估、部署和监控的可复现链路。",
            "把数据版本、模型版本、阈值和评测报告绑定到同一次实验。",
            "按真实部署环境设计交叉验证与盲测，避免随机切分造成数据泄漏。",
            "将错误案例按场景、类别和原因归档，形成下一轮采集计划。",
        ],
        "checks": [
            "能够为数据泄漏、类别不平衡和概念漂移设计检查项。",
            "能够解释准确率、精确率、召回率和混淆矩阵何时更重要。",
            "能够从失败样本反推数据、模型、阈值或业务规则的修订动作。",
        ],
    },
    {
        "number": 4,
        "title": "量化、编译与设备部署",
        "code": "EML-KP-04",
        "level": "core",
        "prerequisites": ["EML-KP-03"],
        "pptx": "Module 4 - Model Deployment/4.3.1.using-a-model-for-inference.1.pptx",
        "docx": "Module 4 - Model Deployment/4.1.1.why-quantization.3.docx",
        "engineering": [
            "比较浮点、动态范围量化和整数量化对体积、速度与误差的影响。",
            "使用代表性数据集校准量化范围，避免只在训练样本上校准。",
            "测量端到端时延、峰值内存和持续功耗，而不是只看模型文件大小。",
            "保留桌面基准与设备基准，定位预处理、推理和后处理的性能瓶颈。",
        ],
        "checks": [
            "能够说明量化误差产生的位置以及校准数据为什么重要。",
            "能够设计设备部署前后的精度一致性检查。",
            "能够给出模型无法满足预算时的结构、算子和输入尺寸调整顺序。",
        ],
    },
    {
        "number": 5,
        "title": "边缘异常检测与阈值治理",
        "code": "EML-KP-05",
        "level": "advanced",
        "prerequisites": ["EML-KP-03"],
        "pptx": "Module 5 - Anomaly Detection/5.3.1.anomaly-detection-in-edge-impulse.1.pptx",
        "docx": "Module 5 - Anomaly Detection/5.1.1.introduction-to-anomaly-detection.3.docx",
        "engineering": [
            "明确正常样本覆盖范围，避免把未知正常工况误判为异常。",
            "将异常分数、业务阈值和告警等级分离，支持不同现场策略。",
            "使用时间窗口、滞回和连续命中规则抑制瞬时噪声告警。",
            "把误报和漏报样本回流到数据集并记录阈值变更原因。",
        ],
        "checks": [
            "能够解释无监督异常检测与监督分类的适用条件。",
            "能够通过分数分布选择初始阈值并设计人工复核区间。",
            "能够描述阈值变化如何影响误报、漏报和现场负担。",
        ],
    },
    {
        "number": 6,
        "title": "嵌入式图像分类与迁移学习",
        "code": "EML-KP-06",
        "level": "advanced",
        "prerequisites": ["EML-KP-02", "EML-KP-03"],
        "pptx": "Module 6 - Image Classification with Deep Learning/6.3.7.transfer-learning-and-mobilenet.2.pptx",
        "docx": "Module 6 - Image Classification with Deep Learning/6.2.10.solution-cnn.3.docx",
        "engineering": [
            "按相机位置、照明、背景和目标姿态设计覆盖真实变化的数据采集。",
            "先训练轻量分类基线，再决定是否需要更大骨干网络或数据增强。",
            "检查输入缩放、颜色通道和归一化在训练端与设备端是否一致。",
            "使用迁移学习缩短训练时间，同时验证预训练特征是否适合目标场景。",
        ],
        "checks": [
            "能够从混淆矩阵识别容易混淆的类别和缺失数据场景。",
            "能够解释数据增强何时提升泛化、何时会破坏标签语义。",
            "能够为相机变化和光照漂移设计回归样本集。",
        ],
    },
    {
        "number": 7,
        "title": "目标检测、定位误差与负责任 AI",
        "code": "EML-KP-07",
        "level": "advanced",
        "prerequisites": ["EML-KP-06"],
        "pptx": "Module 7 - Object Detection/7.1.1.introduction-to-object-detection.2.pptx",
        "docx": "Module 7 - Object Detection/7.1.5.digging-deeper-into-object-detection.2.docx",
        "engineering": [
            "统一边界框标注规则，处理遮挡、截断、小目标和重叠目标。",
            "同时评估分类置信度、定位质量、漏检率和每帧推理时间。",
            "按距离、尺寸、光照和人群属性切片评估，暴露总体指标掩盖的问题。",
            "为低置信度和高风险场景设计拒答、告警或人工确认。",
        ],
        "checks": [
            "能够解释 IoU、非极大值抑制和置信度阈值之间的关系。",
            "能够区分分类错误、定位错误和后处理错误。",
            "能够为高风险检测任务写出可审计的人工接管规则。",
        ],
    },
    {
        "number": 8,
        "title": "关键词唤醒系统与持续监控",
        "code": "EML-KP-08",
        "level": "advanced",
        "prerequisites": ["EML-KP-03"],
        "pptx": "Module 8 - Keyword Spotting/8.3.1.deploy-audio-classifier.1.pptx",
        "docx": "Module 8 - Keyword Spotting/8.1.5.keyword-spotting-application-architecture.3.docx",
        "engineering": [
            "定义唤醒词、未知词和背景噪声三类数据，并覆盖不同说话人与设备。",
            "统一采样率、窗口、步长和频谱特征，保证训练与流式推理一致。",
            "使用滑动窗口、平滑和抑制时间降低重复触发与偶发误触发。",
            "持续记录设备环境中的误触发和漏触发，形成增量评测集。",
        ],
        "checks": [
            "能够解释离线片段准确率为何不能代表持续监听体验。",
            "能够设计每小时误触发次数和真实唤醒召回率的测试。",
            "能够说明噪声、口音、麦克风和距离变化的验证方法。",
        ],
    },
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git_blob(path: str, *, text: bool = False) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(REPOSITORY), "show", f"{REVISION}:{path}"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError(f"frozen_source_missing:{path}")
    raw = result.stdout
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n") if text else raw


def _module_extract(readme: str, number: int) -> tuple[str, str, list[str], list[str]]:
    pattern = rf"(?ms)^### Module {number}:.*?(?=^### Module {number + 1}:|^## Attribution)"
    match = re.search(pattern, readme)
    if not match:
        raise ValueError(f"module_not_found:{number}")
    block = match.group(0)
    heading, _, rest = block.partition("\n")
    intro, marker, remaining = rest.partition("#### Learning Objectives")
    if not marker:
        raise ValueError(f"learning_objectives_not_found:{number}")
    objective_block = remaining.split("#### Section", 1)[0]
    objectives = [item.strip() for item in re.findall(r"(?m)^\d+\.\s+(.+)$", objective_block)]
    sections = re.findall(r"(?m)^#### Section \d+:\s+(.+)$", remaining)
    description = " ".join(line.strip() for line in intro.strip().splitlines() if line.strip())
    return heading.removeprefix("### ").strip(), description, objectives, sections


def _write_license(readme: str) -> tuple[Path, bytes]:
    license_match = re.search(r"(?ms)^## License\n(.*?)(?=^## Professional Development)", readme)
    attribution_match = re.search(r"(?ms)^## Attribution\n(.*)$", readme)
    if not license_match or not attribution_match:
        raise ValueError("upstream_license_or_attribution_missing")
    body = (
        "# License and attribution\n\n"
        f"Frozen source: {REPOSITORY_URL}/tree/{REVISION}\n\n"
        "The bundled upstream slides and sample documents are redistributed for this non-commercial "
        "educational competition under CC BY-NC-SA 4.0. EduMatrix-created summaries, handbook, transcript "
        "and overview video are adaptations and use the same license. No YouTube video is downloaded or bundled.\n\n"
        "## Upstream license notice\n\n"
        + license_match.group(1).strip()
        + "\n\n## Upstream attribution\n\n"
        + attribution_match.group(1).strip()
        + "\n\n## EduMatrix changes\n\n"
        "Chinese module summaries, a course handbook, a transcript and a silent overview video were created "
        "by the EduMatrix team. Binary DOCX and PPTX files remain unchanged from the frozen upstream commit.\n"
    ).encode("utf-8")
    path = OUTPUT_DIR / "LICENSE-AND-ATTRIBUTION.md"
    path.write_bytes(body)
    return path, body


def _wrap_text(text: str, width: int) -> list[str]:
    words = list(text)
    return ["".join(words[index:index + width]) for index in range(0, len(words), width)] or [""]


def _build_handbook(readme_modules: dict[int, dict[str, Any]]) -> tuple[Path, list[dict[str, Any]]]:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    path = OUTPUT_DIR / "materials" / "嵌入式机器学习与边缘智能工程手册.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = A4
    page_regions: list[list[dict[str, Any]]] = []
    current_regions: list[dict[str, Any]] = []
    page_number = 0
    document = canvas.Canvas(str(path), pagesize=A4, pageCompression=1, invariant=1)
    document.setTitle("嵌入式机器学习与边缘智能工程手册")
    document.setAuthor("EduMatrix team; adapted from Edge Impulse courseware")
    document.setSubject("Embedded machine learning engineering course handbook")

    def new_page(title: str, subtitle: str = "") -> None:
        nonlocal current_regions, page_number
        if page_number:
            page_regions.append(current_regions)
            document.showPage()
        page_number += 1
        current_regions = []
        document.setFillColorRGB(0.08, 0.08, 0.08)
        document.rect(0, height - 78, width, 78, fill=1, stroke=0)
        document.setFillColorRGB(1, 1, 1)
        document.setFont("STSong-Light", 20)
        document.drawString(42, height - 48, title)
        if subtitle:
            document.setFont("STSong-Light", 9)
            document.drawRightString(width - 42, height - 47, subtitle)
        document.setFillColorRGB(0.25, 0.25, 0.25)
        document.setFont("STSong-Light", 8)
        document.drawRightString(width - 38, 24, f"EduMatrix · 第 {page_number} 页")

    def block(title: str, items: list[str], y: float) -> float:
        start_y = y
        document.setFillColorRGB(0.12, 0.12, 0.12)
        document.setFont("STSong-Light", 14)
        document.drawString(46, y, title)
        y -= 24
        lines: list[str] = []
        for item in items:
            wrapped = _wrap_text(item, 34)
            lines.extend([f"• {wrapped[0]}", *[f"  {line}" for line in wrapped[1:]]])
        document.setFont("STSong-Light", 10.5)
        document.setFillColorRGB(0.18, 0.18, 0.18)
        for line in lines:
            document.drawString(54, y, line)
            y -= 17
        region_height = max(0.04, (start_y - y + 10) / height)
        current_regions.append({
            "schema_version": "edumatrix.ocr-region.v1",
            "region_id": f"handbook-p{page_number}-r{len(current_regions) + 1}",
            "bbox": {"x": 46 / width, "y": (height - start_y - 8) / height, "width": 0.84, "height": region_height},
            "region_type": "text",
            "content": {"text": title + "\n" + "\n".join(items), "recognition_status": "layout_verified"},
            "privacy": {"sensitive": False, "categories": []},
        })
        return y - 18

    new_page("嵌入式机器学习与边缘智能工程手册", "CC BY-NC-SA 4.0")
    document.setFillColorRGB(0.12, 0.12, 0.12)
    document.setFont("STSong-Light", 28)
    document.drawString(54, height - 190, "从数据到设备的完整工程闭环")
    document.setFont("STSong-Light", 13)
    document.drawString(56, height - 230, "8 个模块 · 真实课件 · 实训检查点 · 来源可追溯")
    block("课程目标", [
        "建立从问题定义、数据采集、模型训练、评估、量化部署到现场监控的完整方法。",
        "能够在设备资源、实时性、隐私和可靠性约束下解释技术取舍。",
        "通过图像、异常检测、目标检测和关键词唤醒案例完成跨模态实践。",
    ], height - 300)

    new_page("课程地图", "学习顺序与能力产出")
    block("建议顺序", [
        "模块 1-3 建立问题定义、神经网络与端到端工作流基础。",
        "模块 4-5 进入量化部署、异常检测和阈值治理。",
        "模块 6-8 完成图像分类、目标检测和关键词唤醒三个综合场景。",
    ], height - 125)
    block("每个模块的完成证据", [
        "阅读模块摘要与上游课件，完成关键概念测验。",
        "根据实训任务书运行代码或分析设备约束，保存输出与解释。",
        "使用检查点复盘错误，形成可追溯的学习记录和下一步计划。",
    ], height - 360)

    for module in MODULES:
        number = module["number"]
        extracted = readme_modules[number]
        new_page(f"模块 {number} · {module['title']}", extracted["upstream_title"])
        y = block("模块说明", [extracted["description"]], height - 125)
        block("学习目标", extracted["objectives"], y)

        new_page(f"模块 {number} · 工程实践", module["title"])
        y = block("实施步骤", module["engineering"], height - 125)
        block("原始课程单元", extracted["sections"], y)

        new_page(f"模块 {number} · 验收与复盘", module["title"])
        y = block("完成检查", module["checks"], height - 125)
        block("证据要求", [
            "记录输入数据、版本、关键参数、输出指标和失败样本。",
            "说明结果是否满足设备与场景约束，不能只给出成功截图。",
            "保留来源页码或章节，保证结论能够回到课程资料复核。",
        ], y)

    new_page("综合实训 · 设备端智能感知", "课程结业任务")
    y = block("任务", [
        "选择图像、声音或传感器异常中的一个场景，定义输入、输出、指标和设备预算。",
        "建立可复现的数据切分与训练基线，完成错误分析和一次有依据的改进。",
        "执行量化或轻量化，比较桌面与设备侧的精度、时延、内存和模型体积。",
    ], height - 125)
    block("提交物", [
        "数据与许可说明、实验配置、模型评测报告、设备部署记录、失败样本与复盘。",
        "一段能够解释系统边界、风险和人工接管条件的技术说明。",
    ], y)

    new_page("来源与使用边界", "可追溯与非商业使用")
    block("来源", [
        f"Edge Impulse courseware，冻结版本 {REVISION}。",
        "上游幻灯片、示例问题和项目任务采用 CC BY-NC-SA 4.0。",
        "本手册是 EduMatrix 团队为比赛演示制作的中文改编材料，采用相同许可证。",
    ], height - 125)
    block("边界", [
        "未下载或重新分发仓库中以标准 YouTube 许可证提供的视频。",
        "课程用于非商业教育与比赛展示，不宣称经过独立行业专家认证。",
        "工程指标为教学检查项，实际产品部署仍需按设备和现场重新验证。",
    ], height - 360)

    page_regions.append(current_regions)
    document.save()
    return path, _render_pdf_pages(path, page_regions)


def _render_pdf_pages(pdf_path: Path, regions: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    import pypdfium2 as pdfium

    asset_dir = OUTPUT_DIR / "reader_pages"
    asset_dir.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(pdf_path.read_bytes())
    pages: list[dict[str, Any]] = []
    try:
        if len(document) != len(regions):
            raise ValueError("handbook_page_region_count_mismatch")
        for index in range(len(document)):
            image = document[index].render(scale=1.6).to_pil().convert("RGB")
            asset_path = asset_dir / f"page-{index + 1:04d}.png"
            image.save(asset_path, format="PNG", optimize=True)
            raw = asset_path.read_bytes()
            pages.append({
                "page_number": index + 1,
                "width_px": image.width,
                "height_px": image.height,
                "image_sha256": _sha256(raw),
                "redacted_image_sha256": _sha256(raw),
                "asset_name": asset_path.name,
                "asset_path": asset_path.relative_to(ROOT).as_posix(),
                "asset_bytes": len(raw),
                "regions": regions[index],
            })
    finally:
        document.close()
    return pages


def _video_font(size: int):
    from PIL import ImageFont

    return ImageFont.truetype(str(Path("C:/Windows/Fonts/simhei.ttf")), size=size)


def _build_video() -> tuple[Path, Path, dict[str, Any]]:
    from PIL import Image, ImageDraw
    import imageio_ffmpeg

    video_dir = OUTPUT_DIR / "media"
    frames_dir = video_dir / "overview_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    slides = [
        ("嵌入式机器学习工程实践", ["从数据到设备", "8 个模块", "真实课程资料与可追溯来源"]),
        ("工程主线", ["问题定义与责任边界", "训练、评估与错误分析", "量化、部署与现场监控"]),
        ("核心场景", ["异常检测", "图像分类与目标检测", "关键词唤醒"]),
        ("学习方式", ["阅读课程资料", "完成实训检查点", "让学习证据回流画像与路径"]),
        ("课程完成标准", ["能解释技术取舍", "能复现实验结果", "能说明失败、风险与下一步"]),
    ]
    for index, (title, bullets) in enumerate(slides):
        image = Image.new("RGB", (1280, 720), "#f4f2ee")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 1280, 92), fill="#171614")
        draw.text((70, 31), "EduMatrix · 垂直课程预置", font=_video_font(28), fill="#ffffff")
        draw.text((84, 166), title, font=_video_font(48), fill="#171614")
        y = 270
        for bullet in bullets:
            draw.ellipse((88, y + 13, 102, y + 27), fill="#6f4e37")
            draw.text((126, y), bullet, font=_video_font(31), fill="#2f2b27")
            y += 86
        draw.text((84, 648), f"{index + 1} / {len(slides)}", font=_video_font(20), fill="#6d6760")
        image.save(frames_dir / f"slide-{index:02d}.png", format="PNG")

    video_path = video_dir / "课程导览_嵌入式机器学习工程实践.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    duration = len(slides) * 5
    command = [
        ffmpeg, "-y", "-framerate", "1/5", "-start_number", "0",
        "-i", str(frames_dir / "slide-%02d.png"),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(duration), "-shortest", "-map_metadata", "-1",
        "-vf", "fps=25,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(video_path),
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not video_path.is_file():
        raise RuntimeError(f"video_generation_failed:{result.stderr[-1000:]}")

    transcript_path = video_dir / "课程导览_转写与画面说明.md"
    transcript = (
        "# 课程导览：嵌入式机器学习工程实践\n\n"
        "本地视频为 EduMatrix 团队制作的 25 秒静音课程导览。画面依次介绍课程定位、工程主线、"
        "核心场景、学习方式和完成标准。视频不冒充语音转写，索引正文来自本说明。\n\n"
        + "\n".join(f"## 画面 {index + 1}：{title}\n\n" + "\n".join(f"- {item}" for item in bullets)
                      for index, (title, bullets) in enumerate(slides))
        + "\n"
    )
    transcript_path.write_text(transcript, encoding="utf-8", newline="\n")
    return video_path, transcript_path, {
        "kind": "video",
        "mime_type": "video/mp4",
        "duration_seconds": duration,
        "audio": "silent_track",
        "transcript_status": "team_authored_visual_description",
    }


def _provenance_entry(
    *,
    order: int,
    title: str,
    source_path: str,
    source_raw: bytes,
    output_path: Path,
    parser_version: str,
    knowledge_point_codes: list[str],
    chapter_key: str,
    chapter_position: int,
    parent_chapter_key: str = "",
    conversion: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    license_path: Path,
    license_raw: bytes,
) -> dict[str, Any]:
    raw = output_path.read_bytes()
    return {
        "chapter_order": order,
        "chapter_key": chapter_key,
        "chapter_position": chapter_position,
        "parent_chapter_key": parent_chapter_key,
        "title": title,
        "repository_key": REPOSITORY_KEY,
        "repository_url": REPOSITORY_URL,
        "git_revision": REVISION,
        "source_path": source_path,
        "source_type": Path(source_path).suffix.lstrip(".").lower() or "md",
        "source_bytes": len(source_raw),
        "source_sha256": _sha256(source_raw),
        "path": output_path.relative_to(OUTPUT_DIR).as_posix(),
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "parser_version": parser_version,
        "conversion": conversion or {"strategy": "unchanged_frozen_binary"},
        "license_spdx": LICENSE_SPDX,
        "license_file": license_path.relative_to(OUTPUT_DIR).as_posix(),
        "license_sha256": _sha256(license_raw),
        "obligations": ["attribution", "noncommercial", "share_alike", "indicate_changes"],
        "attribution": ["Edge Impulse", "Harvard TinyML / Prof. Vijay Janapa Reddi", "EduMatrix team"],
        "knowledge_point_codes": knowledge_point_codes,
        "selection_reason": "课程主线中的真实学习资料，具有冻结来源、明确许可和可复现解析结果。",
        **(extra or {}),
    }


def build_course() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    readme_raw = _git_blob("README.md", text=True)
    readme = readme_raw.decode("utf-8")
    if "CC BY-NC-SA 4.0" not in readme:
        raise ValueError("required_course_license_missing")
    license_path, license_raw = _write_license(readme)

    extracted: dict[int, dict[str, Any]] = {}
    for module in MODULES:
        upstream_title, description, objectives, sections = _module_extract(readme, module["number"])
        extracted[module["number"]] = {
            "upstream_title": upstream_title,
            "description": description,
            "objectives": objectives,
            "sections": sections,
        }

    handbook_path, reader_pages = _build_handbook(extracted)
    video_path, transcript_path, media = _build_video()
    files: list[dict[str, Any]] = []
    processing_rows: list[dict[str, Any]] = []

    handbook_parsed = parse_document(handbook_path.read_bytes(), handbook_path.name)
    files.append(_provenance_entry(
        order=0,
        title="课程导论：嵌入式机器学习与边缘智能工程手册",
        source_path="README.md",
        source_raw=readme_raw,
        output_path=handbook_path,
        parser_version=handbook_parsed.parser_version,
        knowledge_point_codes=[module["code"] for module in MODULES],
        chapter_key="course-overview",
        chapter_position=0,
        conversion={"strategy": "team_authored_pdf_handbook_from_frozen_course_outline", "page_count": len(reader_pages)},
        extra={
            "reader_pages": reader_pages,
            "reader_page_engine": "team_authored_layout_map_v1",
        },
        license_path=license_path,
        license_raw=license_raw,
    ))
    processing_rows.append({"path": files[-1]["path"], "format": "pdf", "text_chars": len(handbook_parsed.text), "warnings": list(handbook_parsed.warnings)})

    video_parsed = parse_document(transcript_path.read_bytes(), transcript_path.name)
    files.append(_provenance_entry(
        order=1,
        title="课程导览视频：从数据到设备",
        source_path="README.md",
        source_raw=readme_raw,
        output_path=video_path,
        parser_version="edumatrix-curated-video-transcript-v1",
        knowledge_point_codes=["EML-KP-01", "EML-KP-03", "EML-KP-04"],
        chapter_key="course-overview-video",
        chapter_position=1,
        parent_chapter_key="course-overview",
        conversion={"strategy": "team_authored_local_video", "external_video_downloaded": False},
        extra={
            "index_text_path": transcript_path.relative_to(OUTPUT_DIR).as_posix(),
            "index_text_bytes": transcript_path.stat().st_size,
            "index_text_sha256": _sha256(transcript_path.read_bytes()),
            "media": media,
        },
        license_path=license_path,
        license_raw=license_raw,
    ))
    processing_rows.append({"path": files[-1]["path"], "format": "mp4", "text_chars": len(video_parsed.text), "warnings": [], "transcript_source": "team_authored"})

    order = 2
    for module in MODULES:
        number = module["number"]
        module_data = extracted[number]
        module_key = f"module-{number}"
        summary_path = OUTPUT_DIR / "chapters" / f"{number:02d}_{module['title']}.md"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary = (
            f"# 模块 {number}：{module['title']}\n\n"
            f"> 上游模块：{module_data['upstream_title']}  \n"
            f"> 固定来源：{REPOSITORY_URL}/blob/{REVISION}/README.md  \n"
            "> 许可证：CC BY-NC-SA 4.0\n\n"
            "## 模块说明\n\n" + module_data["description"] + "\n\n"
            "## 学习目标\n\n" + "\n".join(f"{i}. {item}" for i, item in enumerate(module_data["objectives"], 1)) + "\n\n"
            "## 工程实践\n\n" + "\n".join(f"- {item}" for item in module["engineering"]) + "\n\n"
            "## 完成检查\n\n" + "\n".join(f"- {item}" for item in module["checks"]) + "\n"
        )
        summary_path.write_text(summary, encoding="utf-8", newline="\n")
        summary_parsed = parse_document(summary_path.read_bytes(), summary_path.name)
        files.append(_provenance_entry(
            order=order,
            title=f"模块 {number}：{module['title']}",
            source_path="README.md",
            source_raw=readme_raw,
            output_path=summary_path,
            parser_version=summary_parsed.parser_version,
            knowledge_point_codes=[module["code"]],
            chapter_key=module_key,
            chapter_position=number * 10,
            conversion={"strategy": "bilingual_module_summary_with_team_authored_engineering_checks"},
            license_path=license_path,
            license_raw=license_raw,
        ))
        processing_rows.append({"path": files[-1]["path"], "format": "md", "text_chars": len(summary_parsed.text), "warnings": []})
        order += 1

        for material_index, (kind, source_path) in enumerate((("实验文档", module["docx"]), ("课程课件", module["pptx"])), 1):
            raw = _git_blob(source_path)
            output_path = OUTPUT_DIR / "materials" / f"module-{number:02d}" / Path(source_path).name
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(raw)
            parsed = parse_document(raw, output_path.name)
            files.append(_provenance_entry(
                order=order,
                title=f"{kind}：{Path(source_path).stem}",
                source_path=source_path,
                source_raw=raw,
                output_path=output_path,
                parser_version=parsed.parser_version,
                knowledge_point_codes=[module["code"]],
                chapter_key=f"{module_key}-{kind}",
                chapter_position=number * 10 + material_index,
                parent_chapter_key=module_key,
                license_path=license_path,
                license_raw=license_raw,
            ))
            processing_rows.append({
                "path": files[-1]["path"],
                "format": output_path.suffix.lstrip("."),
                "text_chars": len(parsed.text),
                "location_count": len(parsed.locations),
                "warnings": list(parsed.warnings),
            })
            order += 1

    knowledge_points = [
        {"code": module["code"], "title": module["title"], "level": module["level"], "prerequisites": module["prerequisites"]}
        for module in MODULES
    ]
    manifest = {
        "schema_version": "edumatrix.course-version-manifest.v1",
        "manifest_version": "course-embedded-machine-learning-engineering-2.0.0",
        "generated_at": "2026-08-21T00:00:00+08:00",
        "course_id": COURSE_ID,
        "title": "嵌入式机器学习与边缘智能工程实践",
        "subject": "电子信息 / 人工智能 / TinyML",
        "description": "一门从问题定义、模型训练、评估、量化部署到现场监控的完整垂直课程，含 8 个模块、PDF 工程手册、真实 DOCX/PPTX 课件和本地课程导览视频。",
        "domain_pack": "domain-embedded-machine-learning-engineering-v2",
        "knowledge_point_version": "eml-kp-2.0.0",
        "language": "zh-CN / en",
        "tags": ["嵌入式机器学习", "边缘智能", "TinyML", "工程实践"],
        "content_origin": f"Edge Impulse 开放课程固定版本 {REVISION} 与 EduMatrix 团队改编材料。",
        "license": "CC BY-NC-SA 4.0; attribution and change notice retained in LICENSE-AND-ATTRIBUTION.md.",
        "visibility": "public",
        "status": "published",
        "claim_boundary": "非商业比赛与教学演示课程；不宣称行业认证或独立专家背书。",
        "external_material_policy": "No standard-license YouTube video is downloaded or redistributed.",
        "source_repository": {"key": REPOSITORY_KEY, "url": REPOSITORY_URL, "git_revision": REVISION, "source_path": "README.md", "source_sha256": _sha256(readme_raw)},
        "processing": {"deterministic": True, "network_required": False, "external_model_used": False, "video_transcription_at_startup": False},
        "knowledge_points": knowledge_points,
        "files": files,
    }
    manifest_path = OUTPUT_DIR / "course_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    source_manifest = {
        "schema_version": "edumatrix.course-source-license-manifest.v1",
        "course_id": COURSE_ID,
        "source_repository": manifest["source_repository"],
        "license_spdx": LICENSE_SPDX,
        "license_file": license_path.relative_to(OUTPUT_DIR).as_posix(),
        "youtube_assets_bundled": 0,
        "materials": [{key: item.get(key) for key in ("path", "bytes", "sha256", "source_path", "source_bytes", "source_sha256", "license_spdx", "attribution", "obligations", "conversion")} for item in files],
    }
    (OUTPUT_DIR / "source_license_manifest.json").write_text(
        json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    processing_report = {
        "schema_version": "edumatrix.course-processing-report.v2",
        "course_id": COURSE_ID,
        "source_revision": REVISION,
        "file_count": len(files),
        "format_counts": {suffix: sum(Path(item["path"]).suffix.lower() == suffix for item in files) for suffix in (".md", ".pdf", ".docx", ".pptx", ".mp4")},
        "network_calls": 0,
        "external_model_calls": 0,
        "startup_video_transcription": False,
        "files": processing_rows,
        "manifest_sha256": _sha256(manifest_path.read_bytes()),
    }
    (OUTPUT_DIR / "processing_report.json").write_text(
        json.dumps(processing_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


if __name__ == "__main__":
    result = build_course()
    print(json.dumps({"course_id": result["course_id"], "files": len(result["files"])}, ensure_ascii=False))

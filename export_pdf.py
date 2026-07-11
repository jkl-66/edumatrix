"""
export_pdf.py — 任务 2: 结构化讲义一键生成与 PDF 导出

渲染管线: Markdown → ReportLab → PDF

零外部依赖（纯 Python），支持中英文混排、数学公式、代码块
"""
import re
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.lib.colors import HexColor, black, white, grey
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Preformatted, Table, TableStyle, ListFlowable, ListItem,
    HRFlowable, KeepTogether, Flowable,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ============================================================
# 1. 中文字体注册
# ============================================================

# Windows 常见中文字体路径
_FONT_CANDIDATES = [
    # SimSun (宋体)
    ("SimSun", r"C:\Windows\Fonts\simsun.ttc"),
    ("SimSun", r"C:\Windows\Fonts\SIMFANG.TTF"),
    # Microsoft YaHei (微软雅黑)
    ("MicrosoftYaHei", r"C:\Windows\Fonts\msyh.ttc"),
    ("MicrosoftYaHei", r"C:\Windows\Fonts\msyhbd.ttc"),
    # SimHei (黑体)
    ("SimHei", r"C:\Windows\Fonts\simhei.ttf"),
]

CN_FONT = "Helvetica"  # 默认 fallback
CN_FONT_BOLD = "Helvetica-Bold"

for name, path in _FONT_CANDIDATES:
    if os.path.exists(path):
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            CN_FONT = name
            # 尝试注册粗体版本
            bpath = path.replace('.ttc', 'bd.ttc').replace('.ttf', 'bd.ttf')
            if os.path.exists(bpath):
                pdfmetrics.registerFont(TTFont(f"{name}-Bold", bpath))
                CN_FONT_BOLD = f"{name}-Bold"
            else:
                CN_FONT_BOLD = name
            break
        except Exception:
            continue


# ============================================================
# 2. Markdown → ReportLab 流式元素转换
# ============================================================

# 样式定义
def _make_styles():
    styles = {}
    
    styles['cover_title'] = ParagraphStyle(
        'CoverTitle', fontName=CN_FONT_BOLD, fontSize=24,
        leading=32, alignment=TA_CENTER, textColor=HexColor('#1a1a2e'),
        spaceAfter=12,
    )
    styles['cover_subtitle'] = ParagraphStyle(
        'CoverSubtitle', fontName=CN_FONT, fontSize=13,
        leading=18, alignment=TA_CENTER, textColor=HexColor('#666666'),
        spaceAfter=30,
    )
    styles['cover_meta'] = ParagraphStyle(
        'CoverMeta', fontName=CN_FONT, fontSize=10,
        leading=14, alignment=TA_CENTER, textColor=HexColor('#999999'),
    )
    styles['h1'] = ParagraphStyle(
        'H1', fontName=CN_FONT_BOLD, fontSize=18,
        leading=26, textColor=HexColor('#1a1a2e'),
        spaceBefore=20, spaceAfter=8,
        borderPadding=(0, 0, 4, 0),
    )
    styles['h2'] = ParagraphStyle(
        'H2', fontName=CN_FONT_BOLD, fontSize=15,
        leading=22, textColor=HexColor('#2d3436'),
        spaceBefore=14, spaceAfter=6,
    )
    styles['h3'] = ParagraphStyle(
        'H3', fontName=CN_FONT_BOLD, fontSize=13,
        leading=18, textColor=HexColor('#444444'),
        spaceBefore=10, spaceAfter=4,
    )
    styles['body'] = ParagraphStyle(
        'Body', fontName=CN_FONT, fontSize=10.5,
        leading=18, alignment=TA_JUSTIFY,
        spaceBefore=2, spaceAfter=4,
    )
    styles['code'] = ParagraphStyle(
        'Code', fontName='Courier', fontSize=8,
        leading=12, textColor=HexColor('#2d3436'),
        leftIndent=8, spaceBefore=4, spaceAfter=4,
    )
    styles['bullet'] = ParagraphStyle(
        'Bullet', fontName=CN_FONT, fontSize=10.5,
        leading=17, leftIndent=20, bulletIndent=8,
        spaceBefore=1, spaceAfter=1,
    )
    styles['footer'] = ParagraphStyle(
        'Footer', fontName=CN_FONT, fontSize=8,
        leading=10, alignment=TA_CENTER, textColor=HexColor('#aaaaaa'),
        spaceBefore=30,
    )
    return styles


def _escape_pdf(text: str) -> str:
    """转义 ReportLab Paragraph 的 XML 特殊字符。"""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def _inline_to_pdf(text: str) -> str:
    """将行内 Markdown 标记转换为 ReportLab XML 格式。"""
    # 保护行内公式
    math_spans = []
    def _save_math(m):
        math_spans.append(m.group(0))
        return f'@@INLINEMATH{len(math_spans)-1}@@'
    text = re.sub(r'(?<!\\)\$([^$]+?)(?<!\\)\$', _save_math, text)
    
    # 转义
    text = _escape_pdf(text)
    
    # 加粗 **text**
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # 斜体 *text*
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # 行内代码 `code`
    text = re.sub(r'`([^`]+?)`', r'<font face="Courier" size="8"><b>\1</b></font>', text)
    
    # 恢复行内公式（用斜体表示）
    for i, ms in enumerate(math_spans):
        math_content = ms.strip('$').strip()
        text = text.replace(f'@@INLINEMATH{i}@@', f'<i>{_escape_pdf(math_content)}</i>')
    
    return text


def md_to_flowables(md_text: str, styles: dict) -> list:
    """将 Markdown 文本转换为 ReportLab Flowable 列表。"""
    flowables = []
    lines = md_text.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        if not stripped:
            i += 1
            continue
        
        # 代码块
        if stripped.startswith('```'):
            lang = stripped[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            code_text = '\n'.join(code_lines)
            flowables.append(Spacer(1, 4))
            # Preformatted ä¸æ¯æŒè¾¹æ¡åæ°ï¼ç¨è¡¨æ ¼åè£æ¨¡æè¾¹æ¡
            code_table = Table(
                [[Preformatted(code_text, styles['code'])]],
                colWidths=460,
            )
            code_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f8f9fa')),
                ('BOX', (0, 0), (-1, -1), 0.5, HexColor('#d0d0d0')),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            flowables.append(code_table)
            flowables.append(Spacer(1, 4))
            continue
        
        # 标题
        if stripped.startswith('### '):
            flowables.append(Paragraph(_inline_to_pdf(stripped[4:]), styles['h3']))
        elif stripped.startswith('## '):
            flowables.append(Paragraph(_inline_to_pdf(stripped[3:]), styles['h2']))
        elif stripped.startswith('# '):
            flowables.append(Paragraph(_inline_to_pdf(stripped[2:]), styles['h1']))
        
        # 水平线
        elif re.match(r'^---+\s*$', stripped):
            flowables.append(Spacer(1, 6))
            flowables.append(HRFlowable(width="100%", thickness=0.5,
                                         color=HexColor('#d0d0d0')))
            flowables.append(Spacer(1, 6))
        
        # 无序列表
        elif re.match(r'^[\*\-]\s+', stripped):
            content = re.sub(r'^[\*\-]\s+', '', stripped)
            flowables.append(
                Paragraph(f'&bull; {_inline_to_pdf(content)}', styles['bullet'])
            )
        
        # 有序列表
        elif re.match(r'^\d+\.\s+', stripped):
            num = re.match(r'^(\d+)\.\s+', stripped).group(1)
            content = re.sub(r'^\d+\.\s+', '', stripped)
            flowables.append(
                Paragraph(f'<b>{num}.</b> {_inline_to_pdf(content)}', styles['bullet'])
            )
        
        # 引用
        elif stripped.startswith('> '):
            quote_text = stripped[2:]
            quote_style = ParagraphStyle(
                'Quote', parent=styles['body'],
                leftIndent=16, textColor=HexColor('#555555'),
                fontName=CN_FONT, fontSize=10,
                borderWidth=(0, 0, 0, 2), borderColor=HexColor('#4a6cf7'),
                borderPadding=6,
            )
            flowables.append(Spacer(1, 2))
            flowables.append(Paragraph(_inline_to_pdf(quote_text), quote_style))
            flowables.append(Spacer(1, 2))
        
        # 普通段落
        else:
            flowables.append(Paragraph(_inline_to_pdf(stripped), styles['body']))
        
        i += 1
    
    return flowables


# ============================================================
# 3. PDF 页面模板与生成
# ============================================================

# 封面页眉装饰
_COVER_LOGO = "EduMatrix 智教矩阵"


def _build_cover(title: str, subtitle: str, tags: str, styles: dict) -> list:
    """构建封面页的 flowable 列表。"""
    cover = []
    cover.append(Spacer(1, 80*mm))
    cover.append(Paragraph(
        f'<font color="#888888" size="11">{_escape_pdf(_COVER_LOGO)}</font>',
        ParagraphStyle('Logo', alignment=TA_CENTER, fontName=CN_FONT, fontSize=11)
    ))
    cover.append(Spacer(1, 6))
    cover.append(HRFlowable(width="30%", thickness=1.5,
                             color=HexColor('#4a6cf7'), spaceAfter=16))
    cover.append(Paragraph(_escape_pdf(title), styles['cover_title']))
    if subtitle:
        cover.append(Paragraph(_escape_pdf(subtitle), styles['cover_subtitle']))
    cover.append(Spacer(1, 20))
    cover.append(Paragraph(
        f'生成时间：{datetime.now().strftime("%Y年%m月%d日 %H:%M")}<br/>'
        f'标签：{_escape_pdf(tags)}',
        styles['cover_meta']
    ))
    cover.append(Spacer(1, 40*mm))
    return cover


def generate_note_pdf(
    title: str,
    content: str,
    subtitle: str = "",
    tags: str = "",
    source: str = "学习笔记",
    concepts: Optional[list[str]] = None,
    output_path: Optional[Path] = None,
) -> bytes:
    """
    将笔记内容生成为 PDF（ReportLab 引擎）。

    Args:
        title: 笔记标题
        content: Markdown 格式的笔记内容
        subtitle: 副标题/摘要
        tags: 标签（逗号分隔）
        source: 来源
        concepts: 关联概念列表
        output_path: 可选输出路径

    Returns:
        PDF 文件字节数据
    """
    styles = _make_styles()
    tag_text = tags if tags else (", ".join(concepts) if concepts else "未分类")
    
    # 构建所有 flowable
    story = []
    
    # 封面页
    story.extend(_build_cover(title, subtitle, tag_text, styles))
    story.append(PageBreak())
    
    # 页眉
    header_style = ParagraphStyle(
        'Header', fontName=CN_FONT, fontSize=9,
        textColor=HexColor('#aaaaaa'), alignment=TA_CENTER,
        spaceAfter=12,
    )
    story.append(Paragraph(
        f'<font color="#4a6cf7">◆</font> {_escape_pdf(title)}',
        header_style
    ))
    story.append(HRFlowable(width="100%", thickness=0.3,
                             color=HexColor('#e0e0e0'), spaceAfter=8))
    
    # 正文内容
    body_flowables = md_to_flowables(content, styles)
    story.extend(body_flowables)
    
    # 页脚
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.3,
                             color=HexColor('#e0e0e0'), spaceAfter=8))
    story.append(Paragraph(
        '由 EduMatrix 智教矩阵 · AI 自适应教学系统自动生成',
        styles['footer']
    ))
    
    # 生成 PDF
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            topMargin=2*cm, bottomMargin=2*cm,
            leftMargin=2*cm, rightMargin=2*cm,
            title=title,
            author="EduMatrix",
        )
        doc.build(story)
        pdf_bytes = output_path.read_bytes()
    else:
        from io import BytesIO
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            topMargin=2*cm, bottomMargin=2*cm,
            leftMargin=2*cm, rightMargin=2*cm,
            title=title, author="EduMatrix",
        )
        doc.build(story)
        pdf_bytes = buf.getvalue()
    
    return pdf_bytes


# ============================================================
# 4. 快速测试
# ============================================================

if __name__ == "__main__":
    test = """# \u5377\u79ef\u795e\u7ecf\u7f51\u7edc (CNN) \u7b14\u8bb0

## \u6838\u5fc3\u6982\u5ff5

**\u5377\u79ef\u795e\u7ecf\u7f51\u7edc** \u662f\u4e00\u79cd\u4e13\u95e8\u5904\u7406\u7f51\u683c\u72b6\u6570\u636e\u7684\u6df1\u5ea6\u5b66\u4e60\u6a21\u578b\u3002

### \u5377\u79ef\u5c42
- \u4f7f\u7528\u5377\u79ef\u6838 (kernel) \u63d0\u53d6\u5c40\u90e8\u7279\u5f81
- \u53c2\u6570\u5171\u4eab (weight sharing) \u51cf\u5c11\u53c2\u6570\u91cf

### \u6c60\u5316\u5c42
- \u6700\u5927\u6c60\u5316\u3001\u5e73\u5747\u6c60\u5316

## \u6570\u5b66\u516c\u5f0f

$$\\frac{\\partial L}{\\partial w} = \\frac{1}{m} \\sum_{i=1}^{m} (h_\\theta(x^{(i)}) - y^{(i)}) x^{(i)}$$

## \u4ee3\u7801\u793a\u4f8b

```python
import torch.nn as nn

class CNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 32, 3)
    
    def forward(self, x):
        return self.pool(F.relu(self.conv1(x)))
```

> \u63d0\u793a\uff1aCNN \u7684\u6838\u5fc3\u5728\u4e8e\u5c40\u90e8\u8fde\u63a5\u548c\u53c2\u6570\u5171\u4eab\u3002
"""
    pdf = generate_note_pdf(
        title="\u5377\u79ef\u795e\u7ecf\u7f51\u7edc (CNN) \u5b66\u4e60\u7b14\u8bb0",
        content=test,
        subtitle="\u6df1\u5ea6\u5b66\u4e60\u57fa\u7840",
        tags="\u6df1\u5ea6\u5b66\u4e60, CNN",
        output_path=Path("data/test_export.pdf"),
    )
    print(f"PDF generated: data/test_export.pdf ({len(pdf)} bytes)")
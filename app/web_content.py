"""Shared HTML reading for local files and discovered course materials."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from markdownify import MarkdownConverter


class CourseMarkdownConverter(MarkdownConverter):
    def convert_pre(self, el, text, parent_tags):
        # Syntax highlighting splits a line into many spans. Read their original
        # text directly; stripping each span would corrupt executable indentation.
        content = el.get_text().strip('\r\n')
        classes = [name for node in [el, el.find('code'), *list(el.parents)[:2]]
                   if node is not None for name in node.get('class', [])]
        language = next((match.group(1) for name in classes
                         if (match := re.match(r'(?:language|highlight)-([\w+-]+)$', name)) and match.group(1) not in {'default', 'none'}), '')
        fence = '`' * max(3, max((len(run) + 1 for run in re.findall(r'`+', content)), default=3))
        return f'\n\n{fence}{language}\n{content}\n{fence}\n\n'


def extract_web_material(html: str, *, url: str = '') -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    page_title = soup.title.get_text(' ', strip=True) if soup.title else ''
    author_tag = soup.select_one('meta[name="author"], meta[property="article:author"]')
    author = str(author_tag.get('content') or '') if author_tag else ''
    for tag in soup.select('script, style, noscript, nav, footer, aside, form, button, [role="navigation"], .headerlink, .mdl-tooltip, .d2l-tabs, .toc, .sidebar, .advertisement'):
        tag.decompose()
    candidates = soup.select('article, main, [role="main"], .article-body, .entry-content, .post-content')
    def content_priority(tag):
        named_body = {'article-body', 'entry-content', 'post-content'}.intersection(tag.get('class', []))
        return (3 if tag.get('role') == 'main' or named_body else 2 if tag.name == 'article' else 1, len(tag.get_text()))
    root = max(candidates, key=content_priority, default=soup.body or soup)

    # Preserve genuinely different framework examples, but do not repeat the
    # identical code/output four times just because the original uses tabs.
    for tabs in root.select('.mdl-tabs'):
        labels = {link.get('href', '').lstrip('#'): link.get_text(' ', strip=True)
                  for link in tabs.select('.mdl-tabs__tab-bar a')}
        unique = {}
        for panel in list(tabs.select('.mdl-tabs__panel')):
            key = panel.get_text()
            label = labels.get(panel.get('id', ''), '')
            if key in unique:
                if label:
                    unique[key]['labels'].append(label)
                panel.decompose()
            else:
                unique[key] = {'panel': panel, 'labels': [label] if label else []}
        for bar in tabs.select('.mdl-tabs__tab-bar'):
            bar.decompose()
        for item in unique.values():
            if item['labels']:
                label = soup.new_tag('p')
                strong = soup.new_tag('strong')
                strong.string = ' / '.join(item['labels'])
                label.append(strong)
                item['panel'].insert_before(label)

    replacements = {}
    for math in list(root.select('.math, .katex')):
        if math.parent is None:
            continue
        annotation = math.select_one('annotation[encoding="application/x-tex"]')
        value = annotation.get_text() if annotation else math.get_text().strip()
        if annotation:
            value = f'\\[{value}\\]' if 'katex-display' in (math.parent.get('class') or []) else f'\\({value}\\)'
        number = math.select_one('.eqno')
        if number:
            number_text = number.get_text(strip=True)
            value = value.removeprefix(number_text).strip() + '\n\n' + number_text
        token = f'EDUMATRIXMATH{len(replacements):04d}PLACEHOLDER'
        replacements[token] = value
        math.replace_with(token if value.startswith('\\(') else '\n\n'+token+'\n\n')

    assets = []
    for img in root.find_all('img'):
        src = str(img.get('src') or img.get('data-src') or '')
        resolved = urljoin(url, src)
        allowed = urlparse(resolved).scheme.lower() in {'http', 'https'}
        alt = ' '.join(str(img.get('alt') or '').split())
        figure = img.find_parent('figure') or img.find_parent(class_='figure')
        caption_node = figure.select_one('figcaption, .caption') if figure else None
        caption = caption_node.get_text(' ', strip=True) if caption_node else ''
        index = len(assets) + 1
        assets.append({'asset_id': f'html-image-{index}', 'asset_type': 'image', 'url': resolved,
                       'alt': alt, 'caption': caption, 'position': index,
                       'status': 'pending_authorized_fetch' if allowed else 'blocked',
                       'citation_ready': False, 'ocr_status': 'pending_authorized_fetch' if allowed else 'blocked',
                       'text_source': 'alt' if alt else 'caption' if caption else 'none'})
        # An alt/caption is source text, never a claim that pixels were read.
        token = f'EDUMATRIXIMAGE{index:04d}PLACEHOLDER'
        description = alt or caption or '原网页未提供文字说明'
        link = f' [查看图片]({resolved})' if allowed else ''
        replacements[token] = f'[网页图片 {index}说明] {description}{link}'
        img.replace_with('\n\n'+token+'\n\n')
    for anchor in root.find_all('a', href=True):
        href = urljoin(url, str(anchor['href']))
        if urlparse(href).scheme in {'http', 'https'}:
            anchor['href'] = href
        else:
            anchor.unwrap()
    title_tag = root.find('h1')
    title = title_tag.get_text(' ', strip=True) if title_tag else page_title
    markdown = CourseMarkdownConverter(heading_style='ATX', bullets='-', escape_underscores=False).convert_soup(root).strip()
    for token, value in replacements.items():
        markdown = markdown.replace(token, value)
    return {'title': title, 'author': author, 'url': url, 'markdown': markdown, 'image_assets': assets}

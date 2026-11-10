from app.web_content import extract_web_material
from document_parser import parse_document


def test_course_web_reading_keeps_table_math_code_and_real_link_locations():
    html = r'''<html><head><meta name="author" content="课程编写组"></head><body>
    <nav>站点导航广告</nav><main><h1>误差比较<a class="headerlink" href="#top">¶</a></h1>
    <p>比较两轮训练与验证误差。</p><table><tr><th>轮次</th><th>验证误差</th></tr>
    <tr><td>1</td><td>0.62</td></tr><tr><td>2</td><td>0.30</td></tr></table>
    <div class="math">\[L=\frac{1}{n}\sum_i(y_i-\hat y_i)^2\]</div>
    <pre><code class="language-python">for x in values:
        print(x)
    </code></pre><p><a href="../chapter/gradient.html#step">梯度更新</a></p>
    <figure><img src="../img/curve.png" alt="训练与验证曲线"><figcaption>误差随训练轮次的变化</figcaption></figure>
    </main><footer>无关页脚</footer></body></html>'''
    result = extract_web_material(html, url='https://example.org/course/lesson.html')
    text = result['markdown']
    assert '| 2 | 0.30 |' in text and '| --- | --- |' in text
    assert r'\[L=\frac{1}{n}\sum_i(y_i-\hat y_i)^2\]' in text
    assert 'for x in values:\n        print(x)' in text
    assert '```python' in text
    assert '[梯度更新](https://example.org/chapter/gradient.html#step)' in text
    assert '站点导航广告' not in text and '无关页脚' not in text and '¶' not in text
    assert result['author'] == '课程编写组'
    asset = result['image_assets'][0]
    assert asset['url'] == 'https://example.org/img/curve.png'
    assert asset['citation_ready'] is False and asset['caption'] == '误差随训练轮次的变化'
    parsed = parse_document(html.encode(), 'lesson.html', base_url='https://example.org/course/lesson.html')
    assert parsed.text == text
    assert any(location.kind == 'document' and location.char_end == len(text) for location in parsed.locations)


def test_framework_tabs_deduplicate_only_identical_examples_and_keep_variant_labels():
    html = '''<main><h1>张量转换</h1><div class="mdl-tabs">
    <div class="mdl-tabs__tab-bar"><a href="#a">PyTorch</a><a href="#b">MXNet</a><a href="#c">TensorFlow</a></div>
    <div class="mdl-tabs__panel" id="a"><pre>same_code()</pre></div>
    <div class="mdl-tabs__panel" id="b"><pre>same_code()</pre></div>
    <div class="mdl-tabs__panel" id="c"><pre>different_code()</pre></div></div></main>'''
    text = extract_web_material(html)['markdown']
    assert text.count('same_code()') == 1
    assert 'PyTorch / MXNet' in text and 'TensorFlow' in text
    assert 'different_code()' in text

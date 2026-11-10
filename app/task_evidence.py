"""Assemble existing source passages for a teaching task, without generating text.

Role detection is a retrieval hint, not proof that a claim is supported. Source
scope and current-version checks stay in canonical_retrieval; the answer's
existing verifier still checks the actual statements and quotations.
"""
from __future__ import annotations

import re

from app.cross_language_retrieval import ML_ZH_EN_GLOSSARY, expand_ml_query
from app.retrieval_ranking import rank_chunks


def evidence_roles(text):
    prose = re.sub(r'(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$', '', text)
    math_spans = re.findall(r'\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|(?<!\\)\$[^$\n]+?(?<!\\)\$', prose)
    patterns = {
        # "定义训练函数" announces a programming step; it does not state
        # the concept's meaning. Require a defining predicate, while the
        # procedure/formula roles continue to cover actual implementations.
        'definition': r'定义\s*(?:为|是|如下|[:：])|称为|称作|是指|表示|指的是',
        'condition': r'如果|假设|前提|仅当|只有|当.{0,50}时|其中|取值|非负|大于|小于',
        'procedure': r'```|~~~|首先|接下来|步骤|调用|输入|输出',
        'example': r'例如|比如|示例|例子|\|[^\n]+\||图表|柱状图',
    }
    roles = [role for role, pattern in patterns.items() if re.search(pattern, text if role == 'procedure' else prose, re.S)]
    if any(re.search(r'[=＝+−*/²^]|\\(?:frac|sum|prod|leftarrow|propto)', span.strip('$'), re.S)
           for span in math_spans) or re.search(r'^[^\n$]*[=＝][^\n$]*[+−*/²^]', prose, re.M):
        roles.append('formula')
    # A mention of a chart is not the chart's observations. Keep the data
    # passage independently from the theory used to interpret it.
    if re.search(r'^\s*\|[^\n]*\d[^\n]*\|\s*$', prose, re.M) or (
            re.search(r'横轴|纵轴|图例', prose) and re.search(r'\d', prose)):
        roles.append('chart_data')
    return roles


def _heading_names(title):
    title = re.sub(r'[*`]', '', str(title)).strip()
    if title.startswith('[') and title.endswith(']'):
        title = title[1:-1].strip()
    unnumbered = re.sub(r'^\d+(?:\.\d+)*[.、]?\s+', '', title)
    names = [title, unnumbered]
    bilingual = re.fullmatch(r'([^()（）]+)[(（]([^()（）]+)[)）]', unnumbered)
    if bilingual:
        left, right = (part.strip() for part in bilingual.groups())
        if re.search(r'[\u3400-\u9fff]', left) and re.fullmatch(r'[A-Za-z][A-Za-z0-9 _+./-]*', right):
            names += [left, right]
    return tuple(dict.fromkeys(names))


def _named_topics(text, titles, aliases=None):
    spans = []
    names = [(name, title) for title in set(titles) for name in (aliases or {}).get(title, (title,))]
    for name, title in sorted(names, key=lambda pair: (-len(pair[0]), pair)):
        if len(name.strip()) < 2:
            continue
        pattern = re.escape(name)
        if re.search(r'[A-Za-z]', name) and not re.search(r'[\u3400-\u9fff]', name):
            pattern = r'(?<![A-Za-z0-9_])' + pattern + r'(?![A-Za-z0-9_])'
        for match in re.finditer(pattern, text, re.I):
            if not any(a < match.end() and match.start() < b for a, b, _ in spans):
                spans.append((match.start(), match.end(), title))
                break
    return list(dict.fromkeys(title for _, _, title in sorted(spans)))


def _implementation_request_text(query):
    # A negative instruction still contains the keyword; do not turn "不用
    # 代码" into a code request. Preserve any separate affirmative task.
    return re.sub(r'(?:不用|无需|不要|不需要|不必|不写|不使用)\s*(?:写|提供|生成|使用|编写)?\s*'
                  r'(?:python\s*)?(?:代码|程序|python|编程|运行|打印)', '', query, flags=re.I)


def task_requirements(query, concept_titles=()):
    """Use explicit task words and confirmed course names; no extra planner call."""
    roles = []
    if re.search(r'公式|计算式|表达式|推导|目标函数|损失函数|损失目标|期望|递推|累积|加权平均|分母|分子|变量的?含义|参数.*含义', query):
        roles += ['formula', 'condition']
    elif re.search(r'什么是|定义|含义|是什么意思|规则|判据|判断标准', query):
        roles += ['definition', 'condition']
    if re.search(r'怎样实现|如何实现|操作步骤|编写|运行|实操|演示|打印|代码|python|编程', _implementation_request_text(query), re.I):
        roles += ['procedure', 'example']
    if re.search(r'举例|例子|图表|柱状图', query):
        roles += ['example']
    if re.search(r'条件|前提|适用|保持|不变|等于|大于|小于', query):
        roles += ['condition']
    topics = []
    comparison = bool(re.search(r'比较|对比|区别|差别|各自|分别|异同', query))
    if roles or comparison:
        topics = _named_topics(query, concept_titles)
        # Explicitly named comparison subjects are the methods to cover.
        # Later words such as probability/scaling can be their parameters,
        # not extra textbook chapters that deserve independent source slots.
        parts = re.split(r'分别|各自', query, maxsplit=1)
        if len(parts) == 2 and not re.search(r'另外|此外|还请|再解释|再说明', parts[1]):
            subjects = _named_topics(parts[0], concept_titles)
            coordinated = any(re.search(re.escape(left) + r'\s*(?:和|与|、|以及)\s*' + re.escape(right),
                                        parts[0], re.I) for left, right in zip(subjects, subjects[1:]))
            if len(subjects) >= 2 and coordinated:
                topics = subjects
        if comparison and len(topics) < 2 and not (topics and query.casefold().count(topics[0].casefold()) > 1):
            topics = []
    # A shared named concept can anchor a comparison of its variants. A
    # single unmatched side still retains normal retrieval instead of being
    # presented as both sides of the comparison.
    return {'topics': topics, 'roles': list(dict.fromkeys(roles))}


def estimated_tokens(text):
    # Conservative multilingual estimate, explicitly not the remote tokenizer.
    han = len(re.findall(r'[\u3400-\u9fff]', text))
    return han * 2 + (len(text) - han + 2) // 3


def _passage_units(text):
    """Exact prose units for overlapping exports, not semantic deduplication.

    Keep every character of conditions, numbers and math. Code stays atomic;
    different section titles are checked separately through topic ownership.
    The returned units are only comparison keys, never rewritten quotations.
    """
    if re.search(r'^\s*(?:```|~~~)', text, re.M):
        return {re.sub(r'\s+', '', text)}
    prose = re.sub(r'^\s{0,3}#{1,6}\s+[^\n]*(?:\n|$)', '', text, flags=re.M)
    return {unit for part in re.split(r'(?<=[。！？])|\n\s*\n', prose)
            if (unit := re.sub(r'\s+', '', part))}


def _relation_facets(query):
    """Retain explicitly enumerated parts of a relationship question.

    These are search queries, not inferred knowledge points or proven coverage.
    Algebra and code stay intact; named course comparisons use the existing
    section-aware path instead.
    """
    if not re.search(r'关联|联系|关系|串联|结合|比较|对比|各自|分别|异同|区别', query) or re.search(r'[`$=<>]', query):
        return []
    subject = re.split(r'[，,；;。！？?]', query, maxsplit=1)[0]
    subject = re.sub(r'(?:之间|相互)?(?:如何|怎样|有什么|有何)?(?:关联|联系|关系|串联|结合|各自|分别|异同|区别).*$', '', subject)
    parts = re.split(r'、|以及|与', subject)
    if '、' in subject:
        parts = [*parts[:-1], *re.split(r'和', parts[-1])]
    cleaned = [re.sub(r'^(?:请)?(?:说明|解释|比较|对比)|(?:如何|怎样)$', '', part).strip()
               for part in parts]
    facets = list(dict.fromkeys(part for part in cleaned if len(part) >= 2))
    return facets if len(facets) >= 2 else []


def assemble_task_evidence(chunks, order, rankings, *, query, embeddings,
                           concept_titles=(), top_k=8, token_budget=4000):
    # A course point may cover a whole module. Actual source headings supply
    # the narrower names, without guessing nouns or adding them to the quote.
    generic = {'本章学习目标', '教材正文', '小结', '练习', '总结', '定义', '性质',
               '基础', '实现', '算法', '训练', '模型', '代码实现', '从零开始实现', '简洁实现',
               '演示', '示例', '例子', '实例', '代码', '编程', '实操', '输入', '输出', '比较', '预测', '数据'}
    headings = {name for item in chunks for title in item.metadata.get('title_path', [])
                for name in _heading_names(title)}
    # Function/API comparisons can span sections whose headings name a larger
    # topic. Recognize only identifiers actually used in the allowed passages.
    identifiers = []
    if re.search(r'比较|对比|区别|差别|各自|分别|异同', query):
        for name in re.findall(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*', query):
            pattern = r'(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])\s*\('
            if len(name) >= 3 and any(re.search(pattern, item.content) for item in chunks):
                identifiers.append(name)
    # A term can be defined in the body under a general heading such as
    # "loss function". Reuse known glossary names only when they occur in
    # both the actual question and an allowed source passage.
    glossary_names = [term for entry in ML_ZH_EN_GLOSSARY for term in entry.triggers
                      if re.search(r'[\u3400-\u9fff]', term) and term in query
                      and any(term in item.content for item in chunks)]
    aliases = {}
    for entry in ML_ZH_EN_GLOSSARY:
        if not entry.equivalent_names:
            continue
        mentioned = _named_topics(query, entry.equivalent_names)
        available = [name for name in entry.equivalent_names
                     if any(_named_topics(item.content, [name]) for item in chunks)]
        if mentioned and available:
            # Keep the user's name in the task; match only explicit equivalent
            # names inside allowed sources. Related triggers are never aliases.
            aliases[mentioned[0]] = tuple(dict.fromkeys([mentioned[0], *available]))
    requirements = task_requirements(query, [*concept_titles, *(headings - generic), *identifiers, *glossary_names, *aliases])
    # "Softmax ... probability ... temperature T=1 and T=2" is a method
    # with parameters, not three independent methods to compare. Prefer
    # passages explaining those terms together; explicit method comparisons
    # retain their separate evidence selection.
    joint_topics = (len(requirements['topics']) > 1
                    and not re.search(r'比较|对比|区别|差别|异同|各自', query))
    facets = _relation_facets(query) if len(requirements['topics']) < 2 else []
    by_id = {item.id: item for item in chunks}
    roles = {item.id: evidence_roles(item.content) for item in chunks}
    topic_owners, section_topics, section_distances = {}, {}, {}
    body_only_sections = set()
    for item in chunks:
        # A PDF may expose only a document title and "教材正文". Another
        # document's detailed headings must not make that whole PDF ineligible
        # for body-based topic matching. Meaningful alternative sections still
        # retain the stricter ownership rule below.
        context_title = str(item.metadata.get('document_context') or '').split('\n', 1)[0]
        titles = [re.sub(r'[*`]', '', str(title)).strip('[]() ')
                  for title in item.metadata.get('title_path', [])]
        if not any(title not in generic and title != context_title for title in titles):
            body_only_sections.add(item.id)
        # Prefer the closest named section over an incidental mention of a
        # different method. Long names must not also match their substrings.
        located = next(((distance, found) for distance, title in enumerate(reversed(item.metadata.get('title_path', [])))
                        if (found := _named_topics(str(title), requirements['topics'], aliases))), None)
        named = located[1] if located else []
        exact_distances = [distance for distance, title in enumerate(reversed(item.metadata.get('title_path', [])))
                           if {part.casefold() for part in _heading_names(title)}
                           & {name.casefold() for topic in named for name in aliases.get(topic, (topic,))}]
        section_distances[item.id] = min(exact_distances) if exact_distances else (located[0] if located else 0)
        section_topics[item.id] = named
        topic_owners[item.id] = named or _named_topics(item.content, requirements['topics'], aliases)
    explicitly_sectioned = {topic for topics in section_topics.values() for topic in topics}
    needs = [(topic, role) for topic in (requirements['topics'] or [''])
             for role in (requirements['roles'] or [''])]
    chart_request = bool(re.search(
        r'(?:观察|读取|根据|查看|比较|分析|解释)[^。！？]*(?:柱状图|折线图|图表|表格)|'
        r'(?:柱状图|折线图|图表|表格)[^。！？]*(?:数据|数值|变化|趋势)', query))
    if chart_request:
        needs.insert(0, ('', 'chart_data'))
    if needs == [('', '')] and not facets:
        return order, rankings, {'requirements': requirements, 'applied': False,
                                 'supplemental_queries': [], 'missing_hints': []}

    def matches(key, topic, role):
        owners = (section_topics[key] if topic in explicitly_sectioned and key not in body_only_sections
                  else topic_owners[key])
        return (not topic or topic in owners) and (
            not role or role in roles[key])

    pool = list(order)
    diagnostics = {key: dict(value) for key, value in rankings.items()}
    supplement, preferred = [], {}
    # One supplemental round for the explicitly named course topics.
    # Keep the same allowed candidates: supplementation cannot cross a chosen
    # chapter, source version, course or permission boundary.
    missing = [(topic, role) for topic, role in needs if not any(matches(key, topic, role) for key in pool)]
    topics_to_search = list(dict.fromkeys(topic for topic, _ in missing))
    if requirements['topics'] and requirements['roles']:
        # An overview may contain a rate or a related formula without giving
        # the requested method. Rank within each explicitly named topic too.
        topics_to_search = list(dict.fromkeys([*topics_to_search, *requirements['topics']]))
    labels = {'formula': '公式 变量', 'condition': '适用条件', 'definition': '定义',
              'procedure': '步骤 输入 输出', 'example': '例子 图表', 'chart_data': '图表 数据 数值', '': ''}
    for topic in topics_to_search:
        descriptions = ' '.join(labels[role] for name, role in needs if name == topic)
        # Keep conceptual qualifiers (coefficient range, coordinate-wise
        # operations, etc.). A concrete code example already has its full
        # input in the original search; its supplemental route seeks the
        # concept's rules without repeating sample numbers and print details.
        concrete_code = bool(re.search(r'代码|编写|编程|python', _implementation_request_text(query), re.I)
                             and re.search(r'\d', query))
        remainder = query
        for name in sorted(requirements['topics'], key=len, reverse=True):
            remainder = re.sub(re.escape(name), ' ', remainder, flags=re.I)
        remainder = re.sub(r'比较|对比|区别|差别|各自|分别|异同|与|和|、', ' ', remainder)
        context = '' if concrete_code else remainder
        subquery = f'{topic} {context} {descriptions}'.strip() if topic else f'{query} {descriptions}'.strip()
        scoped = [item for item in chunks if not topic or matches(item.id, topic, '')]
        ranked, detail, execution = rank_chunks(scoped or chunks, query=subquery,
            expanded_query=expand_ml_query(subquery).expanded_query, embeddings=embeddings)
        supplement.append({'query': subquery, 'retrieval': execution})
        preferred[topic] = [key for key in ranked if not topic or matches(key, topic, '')]
        for key in ranked:
            if topic and not matches(key, topic, ''):
                continue
            if key not in diagnostics:
                # Never present a supplemental query's ranking as the original
                # question's ranking or probability of factual support.
                diagnostics[key] = {'lexical_rank': None, 'lexical_score': 0,
                    'semantic_rank': None, 'semantic_score': None, 'fused_score': None}
            diagnostics[key].setdefault('supplemental_rankings', []).append({'query': subquery, **detail[key]})
            if key not in pool:
                pool.append(key)

    facet_matches = {}
    for facet in facets:
        ranked, detail, execution = rank_chunks(chunks, query=facet,
            expanded_query=expand_ml_query(facet).expanded_query, embeddings=embeddings)
        supplement.append({'query': facet, 'kind': 'explicit_relationship_part', 'retrieval': execution})
        relevant = [key for key in ranked if float(detail[key].get('lexical_score') or 0) > 0
                    or float(detail[key].get('semantic_score') or 0) >= .60]
        if relevant:
            key = relevant[0]
            facet_matches[facet] = key
            if key not in diagnostics:
                diagnostics[key] = {'lexical_rank': None, 'lexical_score': 0,
                    'semantic_rank': None, 'semantic_score': None, 'fused_score': None}
            diagnostics[key].setdefault('supplemental_rankings', []).append({'query': facet, **detail[key]})
            diagnostics[key].setdefault('task_facet_matches', []).append(facet)
            if key not in pool:
                pool.append(key)

    chosen, seen, used = [], set(), 0
    covered_units, redundant = {}, set()
    equation_targets = {}
    equation_refs = {}
    if 'formula' in requirements['roles']:
        for item in chunks:
            source = item.metadata.get('document_source') or item.source
            labels = re.findall(r':eqlabel:`([^`]+)`|\\label\{([^}]+)\}', item.content)
            if 'formula' in roles[item.id]:
                for pair in labels:
                    equation_targets.setdefault((source, next(filter(None, pair))), []).append(item.id)
            equation_refs[item.id] = [(source, next(filter(None, pair))) for pair in
                re.findall(r':eqref:`([^`]+)`|\\eqref\{([^}]+)\}', item.content)]

    def add(key):
        nonlocal used
        if key in chosen or len(chosen) >= top_k:
            return
        text = by_id[key].content
        owners = tuple(topic_owners[key])
        fingerprint = (owners, re.sub(r'\s+', '', text))
        if fingerprint in seen:
            return
        # The same textbook can be supplied as Markdown and a PDF export.
        # An overlapping paragraph adds no evidence when every prose unit
        # already exists under the same named topics. A new condition,
        # number, equation, or code block still reserves its own passage.
        units = _passage_units(text)
        if owners and units and units <= covered_units.get(owners, set()):
            redundant.add(key)
            return
        cost = estimated_tokens(text)
        if chosen and used + cost > token_budget:
            return
        chosen.append(key); seen.add(fingerprint); used += cost
        if owners:
            covered_units.setdefault(owners, set()).update(units)

    def add_equation_dependencies():
        # Textbook paragraphs can explain an equation by its explicit label.
        # Resolve only unambiguous targets already inside the permitted source
        # candidates; do not invent an adjacent span or search another version.
        position = 0
        while position < len(chosen):
            owner = chosen[position]
            position += 1
            for reference in equation_refs.get(owner, []):
                targets = equation_targets.get(reference, [])
                if len(targets) != 1:
                    continue
                key = targets[0]
                if key not in diagnostics:
                    diagnostics[key] = {'lexical_rank': None, 'lexical_score': 0,
                        'semantic_rank': None, 'semantic_score': None, 'fused_score': None}
                diagnostics[key].setdefault('equation_referenced_by', [])
                if owner not in diagnostics[key]['equation_referenced_by']:
                    diagnostics[key]['equation_referenced_by'].append(owner)
                add(key)

    # Retain the strongest original match, then give each explicit requirement
    # an opportunity before filling with the remaining ranked passages.
    def ordered_matches(topic, role):
        keys = list(dict.fromkeys(preferred.get(topic, []) + pool))
        keys = [key for key in keys if matches(key, topic, role)]
        if topic in explicitly_sectioned:
            # A nested extension (e.g. a preconditioned variant) must not
            # displace its method's own definition merely by mentioning it.
            # Introductory formulas at the chapter root are not necessarily
            # the method's defining formula. Its ordinary subsections remain
            # peers; deeper variants still follow the basic explanation.
            keys.sort(key=lambda key: max(0, section_distances[key] - 1))
        if joint_topics:
            primary = requirements['topics'][0]
            keys.sort(key=lambda key: (not matches(key, primary, ''),
                -sum(matches(key, name, '') for name in requirements['topics'])))
        if role == 'procedure' and requests_code:
            keys.sort(key=lambda key: not has_code(key))
        return keys

    requests_code = bool(re.search(r'代码|编写|编程|python', _implementation_request_text(query), re.I))
    def has_code(key):
        return bool(re.search(r'^\s*(?:```|~~~)', by_id[key].content, re.M))

    if pool:
        add(pool[0])
    for key in facet_matches.values():
        add(key)
    for topic, role in needs:
        primary_detail = bool(requirements['roles']) and role == requirements['roles'][0] and topic in preferred
        code_detail = (role == 'procedure' and requests_code
                       and any(has_code(key) for key in ordered_matches(topic, role)))
        if not primary_detail and any(matches(key, topic, role) and (not code_detail or has_code(key)) for key in chosen):
            continue
        candidate = next(iter(ordered_matches(topic, role)), None)
        if candidate:
            add(candidate)
    add_equation_dependencies()
    if len(requirements['topics']) > 1 and requirements['roles']:
        primary_role = requirements['roles'][0]
        by_topic = [ordered_matches(topic, primary_role) for topic in requirements['topics']]
        # Give each requested method its next explanatory passage before one
        # popular method consumes all remaining slots (definition + update).
        for position in range(max((len(keys) for keys in by_topic), default=0)):
            for keys in by_topic:
                if position < len(keys):
                    add(keys[position])
                    add_equation_dependencies()
    if len(requirements['topics']) == 1 and requirements['roles']:
        for key in ordered_matches(requirements['topics'][0], requirements['roles'][0]):
            add(key)
            add_equation_dependencies()
    for key in pool:
        add(key)
        add_equation_dependencies()
    missing = [{'topic': topic, 'role': role} for topic, role in needs
               if not any(matches(key, topic, role) for key in chosen)]
    for key in chosen:
        diagnostics[key]['task_topic_matches'] = [topic for topic in requirements['topics'] if matches(key, topic, '')]
    return chosen, diagnostics, {'requirements': requirements, 'applied': True,
        'supplemental_queries': supplement, 'missing_hints': missing,
        'selected_ids': chosen, 'estimated_tokens': used, 'estimated_token_budget': token_budget,
        'redundant_overlap_ids': sorted(redundant),
        'whole_passage_exceeds_budget': used > token_budget,
        'relationship_parts': facets,
        'missing_relationship_parts': [facet for facet in facets if facet_matches.get(facet) not in chosen],
        'unresolved_equation_references': list(dict.fromkeys(label for key in chosen
            for source, label in equation_refs.get(key, [])
            if len(equation_targets.get((source, label), [])) != 1
            or equation_targets[(source, label)][0] not in chosen)),
        'role_hints': {key: roles[key] for key in chosen}}

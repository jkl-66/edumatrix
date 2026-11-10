"""Continue an oversized teaching document in complete, reusable model batches.

This is the overflow path of the existing generator. It returns the same payload
and still goes through normal resource validation and review before publication.
"""
from __future__ import annotations

import hashlib
import json
from copy import copy
from typing import Any, Callable

from llm_client import ModelOutputLimitError, parse_json_object


def generation_parts_key(system: str, user: str, backend: Any) -> str:
    inputs = ["resource-parts-v1", system, user, str(getattr(backend, "model", "")),
              str(getattr(backend, "reasoning_effort", ""))]
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False).encode()).hexdigest()


async def generate_document_parts(
    backend: Any, *, resource_type: str, system: str, user: str,
    completed: dict[str, dict[str, Any]], save: Callable[[str, dict[str, Any]], None],
) -> dict[str, Any]:
    """Generate all planned sections; retries reuse only identical frozen inputs."""
    if resource_type not in {"handout", "deck"}:
        return await generate_structured_parts(backend, resource_type=resource_type,
            system=system, user=user, completed=completed, save=save)
    base = generation_parts_key(system, user, backend)
    completed[base + ":started"] = {"started": True}
    save(base + ":started", {"started": True})
    generator = copy(backend)
    if isinstance(getattr(generator, "max_tokens", None), int):
        generator.max_tokens = max(generator.max_tokens, 65536)
    section_field = "handoutSections" if resource_type == "handout" else "slides"
    original = json.loads(user)
    part_system = (
        system + "\n【分段续写】本次只完成part_request指定的部分，返回一个完整JSON对象。"
        "不要重复生成其他字段，不省略本部分的实际教学内容。分段仅为适应单次输出容量，"
        "完整范围、用户要求的数量、教学深度与质量条件保持不变。completed_content和section_plan"
        "是同份资源的已保存内容，延续其术语、示例、数值和教法；不要声称未提供的内容已存在。"
        "sections阶段每个章节必须额外返回数值index，逐项等于sections_to_write中的index，"
        "用于对应已规划章节；原资源的id字段不能代替index。只返回本批指定章节。"
    )
    if resource_type == "handout":
        part_system += (
            "plan/sections阶段按教学顺序规划讲解、已解例题及需在开头或中途独立尝试的kind=task章节。"
            "task的content只写完整题设，hint给可选方法，successCheck给完成后核对；核对不复制进普通正文。"
            "已掌握的能力可先task再回看方法。其余小测与末尾迁移留到checks阶段，不在正文写它们的答案解析章节。"
            "最终checks阶段生成quizQuestions与transferQuestions，不重复已有task章节；小测答案只放answer/explanation，"
            "分级方法提示放hints，迁移核对只放successCheck，不复制到正文、概述或practiceSteps。"
            "回顾章节只整理方法与概念，不能提前泄露最终checks阶段的独立任务答案。"
            "本次用户给定的主例保留原对象、数值、条件并在正文完整解答；为避免重复，应改变最终检查题而不是主例。"
        )

    async def call(request: dict[str, Any], valid: Callable[[dict[str, Any]], bool],
                   explain: Callable[[dict[str, Any]], str] | None = None,
                   *, allow_split: bool = True) -> dict[str, Any]:
        packet = {**original, "part_request": request}
        text = json.dumps(packet, ensure_ascii=False, sort_keys=True)
        key = base + ":" + hashlib.sha256(text.encode()).hexdigest()
        cached = completed.get(key)
        if isinstance(cached, dict) and valid(cached):
            return cached
        failure = completed.get(key + ':invalid')
        for _ in range(2):
            prompt = part_system
            current = dict(packet)
            if failure:
                current['part_correction'] = failure
                prompt += "\n上一部分结构不完整：" + failure['error'] + "请只纠正当前部分，保留完整正文。"
            try:
                if key + ':overflow' in completed:
                    raise ModelOutputLimitError(completed[key + ':overflow']['error'])
                raw = await generator.generate(prompt, json.dumps(current, ensure_ascii=False, sort_keys=True),
                                               role="resource_generator")
            except ModelOutputLimitError as exc:
                if key + ':overflow' not in completed:
                    completed[key + ':overflow'] = {'error': str(exc)}
                    save(key + ':overflow', completed[key + ':overflow'])
                if not allow_split:
                    raise
                # A single long chapter (or checks/code field) still needs
                # continuation. Split its JSON values, retaining prior sections.
                original_part = current.pop('part_request')
                current['document_part_request'] = original_part
                split_system = prompt + ("\n现在按字段继续document_part_request指定的这一部分，"
                    "它规定最终对象的字段、章节索引与完整范围。part_request仅指定本次要写的JSON子字段。"
                    "不能重新规划整份文档或省略这一节的正文、代码、题目或核对内容。")
                output = await generate_structured_parts(generator, resource_type=resource_type,
                    system=split_system, user=json.dumps(current, ensure_ascii=False, sort_keys=True),
                    completed=completed, save=save)
                raw = json.dumps(output, ensure_ascii=False)
            try:
                output = parse_json_object(raw)
                if not valid(output):
                    raise ValueError(explain(output) if explain else "按part_request的字段、索引与完成标记核对。")
            except (ValueError, KeyError, TypeError) as exc:
                failure = {'raw': raw, 'error': str(exc)}
                completed[key + ':invalid'] = failure
                save(key + ':invalid', failure)
                save(key + ':invalid:' + hashlib.sha256(raw.encode()).hexdigest(), failure)
                continue
            completed[key] = output
            save(key, output)
            return output
        raise ValueError("这一部分尚未生成完整：" + failure['error'])

    header_fields = ("summary", "narrative", "learningGoal")
    header = await call({
        "stage": "overview", "return_fields": [*header_fields, "estimatedMinutes"],
        "instruction": "给出本资源目标及简明串联回顾；完整讲解随后按节写，不在此重复全文。",
    }, lambda value: all(isinstance(value.get(k), str) and value[k].strip() for k in header_fields))
    payload = {k: header[k] for k in (*header_fields, "estimatedMinutes") if k in header}

    # There is a per-request batch size, but no cap on the complete document.
    plan: list[dict[str, Any]] = []
    complete = False
    batch_size = 8
    while not complete:
        start = len(plan)

        def valid_plan(value):
            rows = value.get("section_plan")
            return (isinstance(value.get("complete"), bool) and isinstance(rows, list)
                    and bool(rows)
                    and all(isinstance(row, dict) and row.get("index") == start + i
                            and str(row.get("title") or "").strip()
                            and str(row.get("objective") or "").strip()
                            for i, row in enumerate(rows)))
        try:
            part = await call({
                "stage": "plan", "start_index": start, "batch_size": batch_size,
                "completed_content": payload, "section_plan": plan,
                "instruction": "按已确认教法接着规划后续章节；返回section_plan数组，每项index、title、kind、objective。"
                    "index从start_index开始连续。尚未覆盖全部要求时complete=false；全部章节规划完才complete=true。"
                    "不重复已规划章节，每节应能在一次请求中完整讲解；长章拆成有清楚目标的小节。"
                    "若用户明确要求页数或章节数，规划到该数量，不因batch_size省略后续。",
            }, valid_plan, allow_split=batch_size == 1)
        except ModelOutputLimitError:
            if batch_size == 1:
                raise
            batch_size = max(1, batch_size // 2)
            continue
        plan.extend(part["section_plan"])
        complete = part["complete"]

    sections: list[dict[str, Any]] = []
    batch_size = 2
    while len(sections) < len(plan):
        selected = plan[len(sections):len(sections) + batch_size]
        expected = [row["index"] for row in selected]

        def valid_sections(value):
            rows = value.get(section_field)
            if not isinstance(rows, list) or len(rows) != len(selected):
                return False
            if [row.get("index") if isinstance(row, dict) else None for row in rows] != expected:
                return False
            for row in rows:
                if not str(row.get("title") or "").strip():
                    return False
                if resource_type == "handout":
                    if not str(row.get("content") or row.get("code") or "").strip():
                        return False
                    if row.get("kind") == "task" and not str(row.get("successCheck") or "").strip():
                        return False
                elif not (str(row.get("body") or "").strip() or row.get("bullets") or row.get("layout") == "title"):
                    return False
            return True

        def explain_sections(value):
            rows = value.get(section_field)
            if not isinstance(rows, list):
                return f"缺少数组{section_field}，本批须返回index={expected}的章节。"
            issues = []
            if len(rows) != len(selected):
                issues.append(f"本批须返回{len(selected)}节，实际返回{len(rows)}节")
            for pos, expected_index in enumerate(expected):
                if pos >= len(rows):
                    break
                row = rows[pos]
                prefix = f"{section_field}[{pos}]"
                if not isinstance(row, dict):
                    issues.append(prefix + "必须是章节对象")
                    continue
                if row.get("index") != expected_index:
                    issues.append(f"{prefix}.index缺失或不匹配，必须为数值{expected_index}；id不能代替index")
                if not str(row.get("title") or "").strip():
                    issues.append(prefix + "缺少title")
                if resource_type == "handout" and not str(row.get("content") or row.get("code") or "").strip():
                    issues.append(prefix + "缺少完整content或code")
                elif resource_type == "handout" and row.get("kind") == "task" and not str(row.get("successCheck") or "").strip():
                    issues.append(prefix + "的task缺少完成后核对successCheck，题设content不要包含该答案")
                elif resource_type == "deck" and not (str(row.get("body") or "").strip() or row.get("bullets") or row.get("layout") == "title"):
                    issues.append(prefix + "缺少正文body或bullets")
            return "；".join(issues) + "。"

        try:
            part = await call({
                "stage": "sections", "return_field": section_field, "sections_to_write": selected,
                "section_plan": plan, "completed_content": {**payload, section_field: list(sections)},
                "previous_section": sections[-1] if sections else None,
                "instruction": f"仅返回{section_field}数组，逐项包含原计划index及该类型要求的完整正文字段。"
                    "不重复其他章节，不用摘要代替讲解；代码、题设和推导必须完整。后续章节仍会继续生成。",
            }, valid_sections, explain_sections, allow_split=batch_size == 1)
        except ModelOutputLimitError:
            if batch_size == 1:
                raise
            batch_size = 1
            continue
        for row in part[section_field]:
            section = {k: v for k, v in row.items() if k != "index"}
            section["id"] = f"section-{row['index'] + 1}"
            sections.append(section)
    payload[section_field] = sections

    if resource_type == "handout":
        for stage, fields in [
            ("practice", ["practiceSteps", "starterCode", "codeExplanation"]),
            ("checks", ["quizQuestions", "misconceptions", "transferQuestions"]),
        ]:
            required = ["practiceSteps"] if stage == "practice" else ["quizQuestions"]
            part = await call({
                "stage": stage, "return_fields": fields, "completed_content": payload,
                "instruction": "对照已保存正文补齐本组字段；题号、题设、答案、代码和数据须一致。"
                    "遵守原要求中的题目与步骤结构，不重写已保存章节。practiceSteps只概括学习流程；"
                    "starterCode仅在本次主题和要求需要编程时复用已有完整代码，不重写等价示例；否则省略或留空，纸笔记录与清单放普通正文。独立迁移题使用正文未解完的新条件，"
                    "完整答案仅放successCheck；小测若复用例题，定位为回顾，不宣称检验独立迁移。"
                    "拟好迁移题后独立计算，再与正文已解结果对照；只换输入却仍能照抄全部所问结论的题不是新迁移。"
                    "新任务可运用已教原理，但必须有仍需学习者完成的具体判断或计算，不为制造差异删除必要教学。",
            }, lambda value: all(value.get(k) for k in required))
            payload.update({k: part[k] for k in fields if k in part})
    return payload


def _schema_allows_null(root, path):
    """Follow the supplied output schema, including Pydantic refs and unions.

    A model-authored field plan cannot override a nullable schema with a single
    kind. The caller still validates the assembled object against its full model.
    """
    def variants(schema, seen=frozenset()):
        if not isinstance(schema, dict):
            return []
        ref = schema.get('$ref')
        if isinstance(ref, str) and ref.startswith('#/'):
            if ref in seen:
                return []
            target = root
            for key in ref[2:].split('/'):
                target = target.get(key.replace('~1', '/').replace('~0', '~'), {}) if isinstance(target, dict) else {}
            return variants(target, seen | {ref})
        choices = schema.get('anyOf') or schema.get('oneOf')
        return [v for choice in choices for v in variants(choice, seen)] if choices else [schema]

    schemas = variants(root)
    for key in path:
        children = []
        for schema in schemas:
            if isinstance(key, str):
                child = schema.get('properties', {}).get(key)
            else:
                prefix = schema.get('prefixItems', [])
                child = prefix[key] if 0 <= key < len(prefix) else schema.get('items')
            children.extend(variants(child))
        schemas = children
    return any(schema.get('type') == 'null' or
        (isinstance(schema.get('type'), list) and 'null' in schema['type']) for schema in schemas)


async def generate_structured_parts(backend, *, resource_type, system, user, completed, save):
    """Decompose oversized JSON by fields/items; preserve every completed value.

    The same resource schema and downstream validation apply. Object plans and
    array plans paginate without a total item limit; long strings append exact
    chunks. A failed child never restarts its siblings.
    """
    base = generation_parts_key(system, user, backend)
    completed[base + ":started"] = {"started": True}
    save(base + ":started", {"started": True})
    original = json.loads(user)
    generator = copy(backend)
    instruction = (system + "\n本次分段完成同一JSON资源，严格只完成part_request。"
        "原资源必需字段、数量、教学深度、全部数据和原选类型保持不变。"
        "已保存字段和计划是当前资源的真实上下文，不重复生成或改变已完成数据。"
        "value阶段只返回{value:所求JSON值}；plan阶段返回entries和complete，"
        "每项包含key（对象字段名或数组从0开始的索引）、kind(object/array/string/number/boolean/null)、"
        "objective（该字段或条目完整具体要求）。plan只规划当前层，子层随后完成。"
        "text阶段返回text和complete；text只接续指定字符串，不重写前缀。"
        "只返回完整JSON；complete=true仅表示当前完整范围已经结束。")

    async def call(request, validate):
        packet = {**original, "part_request": request}
        encoded = json.dumps(packet, ensure_ascii=False, sort_keys=True)
        key = base + ":structured:" + hashlib.sha256(encoded.encode()).hexdigest()
        if key in completed:
            try:
                validate(completed[key])
                return completed[key]
            except (ValueError, KeyError, TypeError):
                # Old caches may contain a malformed part; never reuse it as a
                # successful sibling or lose its original response.
                failure = {"raw": json.dumps(completed.pop(key), ensure_ascii=False),
                           "error": "原缓存未通过本部分字段、类型或索引校验。"}
                completed[key + ':invalid'] = failure
                save(key + ':invalid', failure)
        failure = completed.get(key + ':invalid')
        if failure and isinstance(failure.get('raw'), str):
            # A corrected schema check can accept a previously rejected value
            # (e.g. nullable path revisions). Keep the old failure as evidence,
            # but do not send obsolete correction instructions to the model.
            try:
                previous = parse_json_object(failure['raw'])
                validate(previous)
            except (ValueError, KeyError, TypeError):
                pass
            else:
                completed[key] = previous
                save(key, previous)
                return previous
        for _ in range(2):
            packet = {**original, 'part_request': request}
            if failure:
                packet['part_correction'] = failure
            raw = await generator.generate(instruction + (
                '\npart_correction保留上一份未通过校验的原稿及具体错误，只纠正当前部分。' if failure else ''),
                json.dumps(packet, ensure_ascii=False, sort_keys=True), role='resource_generator')
            try:
                output = parse_json_object(raw)
                validate(output)
            except (ValueError, KeyError, TypeError) as exc:
                failure = {'raw': raw, 'error': str(exc)}
                completed[key + ':invalid'] = failure
                save(key + ':invalid', failure)
                save(key + ':invalid:' + hashlib.sha256(raw.encode()).hexdigest(), failure)
                continue
            completed[key] = output
            save(key, output)
            return output
        raise ValueError(f"分段内容尚需纠正：{failure['error']}")

    def matches(value, kind):
        return {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
                "string": lambda: isinstance(value, str), "number": lambda: type(value) in (int, float),
                "boolean": lambda: isinstance(value, bool), "null": lambda: value is None}[kind]()

    async def build(path, kind, objective, context, *, split=False):
        nullable = _schema_allows_null(original.get('output_schema', {}), path)
        value_request = {"stage": "value", "path": path, "kind": kind, "objective": objective,
                         "completed_content": context}
        if not split:
            try:
                def validate_value(output):
                    if 'value' not in output or not (matches(output['value'], kind)
                            or (nullable and output['value'] is None)):
                        raise ValueError(f"分段字段{path}必须返回value且类型为{kind}")
                return (await call(value_request, validate_value))["value"]
            except ModelOutputLimitError:
                pass
        if kind in {"number", "boolean", "null"}:
            raise ValueError(f"标量字段{path}尚未生成完整")
        if kind == "string":
            chunks = []
            chunk_size = 6000
            while True:
                def validate_text(part):
                    chunk = part.get('text')
                    if (not isinstance(chunk, str) or not isinstance(part.get('complete'), bool)
                            or (not chunk and not (chunks and part['complete'])) or (chunk and chunk in chunks)):
                        raise ValueError(f"字符串{path}须返回新增text及布尔complete，不能重复已保存片段")
                try:
                    part = await call({**value_request, "stage": "text", "completed_text": "".join(chunks),
                        "chunk_number": len(chunks), "suggested_characters": chunk_size,
                        "instruction": "接续本批正文或代码，不重复前缀；完整内容超出本批时complete=false继续。"}, validate_text)
                except ModelOutputLimitError:
                    if chunk_size <= 1:
                        raise
                    chunk_size = max(1, chunk_size // 2)
                    continue
                chunks.append(part['text'])
                if part["complete"]:
                    return "".join(chunks)
        plan = []
        keys = set()
        batch_size = 4
        while True:
            def validate_plan(part):
                entries = part.get('entries')
                if not isinstance(entries, list) or not isinstance(part.get('complete'), bool) or (not entries and not part['complete']):
                    raise ValueError(f"字段{path}须返回entries及布尔complete")
                seen = set(keys)
                for i, entry in enumerate(entries):
                    if not isinstance(entry, dict) or entry.get('kind') not in {'object', 'array', 'string', 'number', 'boolean', 'null'}:
                        raise ValueError(f"字段{path}第{i}项缺少有效kind")
                    key = entry.get('key')
                    if ((kind == 'object' and (not isinstance(key, str) or not key))
                            or (kind == 'array' and (type(key) is not int or key != len(plan) + i))):
                        raise ValueError(f"字段{path}第{i}项key应为字段名或连续数组索引{len(plan) + i}")
                    if key in seen or not str(entry.get('objective') or '').strip():
                        raise ValueError(f"字段{path}第{i}项重复或缺少objective")
                    seen.add(key)
            try:
                part = await call({**value_request, 'stage': 'plan', 'planned_entries': plan,
                    'batch_size': batch_size, 'instruction': '按batch_size规划本批，objective简短定位内容，实际正文后续写；剩余继续，不省略原要求。'}, validate_plan)
            except ModelOutputLimitError:
                if batch_size == 1:
                    raise
                batch_size = max(1, batch_size // 2)
                continue
            for entry in part['entries']:
                keys.add(entry['key'])
                plan.append(entry)
            if part["complete"]:
                break
        result = {} if kind == "object" else []
        for entry in plan:
            value = await build([*path, entry["key"]], entry["kind"], entry["objective"],
                                {"parent": context, "plan": plan, "completed_siblings": result})
            if kind == "object":
                result[entry["key"]] = value
            else:
                result.append(value)
        return result

    return await build([], "object", f"完成{resource_type}原要求全部字段与内容", {}, split=True)

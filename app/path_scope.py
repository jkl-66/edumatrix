"""Read a task's teaching scope from its existing immutable plan version."""
import re

from app.database import DBLearningPath, DBPlanVersion


def plan_step_names(content):
    """Resolve prose references against the displayed order of this version."""
    return {item['node_key']: f"{index} · {item['title']}"
            for index, item in enumerate((content or {}).get('nodes', []), 1)
            if item.get('node_key') and item.get('title')}


def path_node_content(session, node):
    path = session.get(DBLearningPath, node.learning_path_id)
    version = session.get(DBPlanVersion, path.source_plan_version_id) if path else None
    return next((item for item in (version.content or {}).get('nodes', [])
                 if item.get('node_key') == node.node_key), {}) if version else {}


def is_staged_node(node):
    return bool(re.search(r"-part-[1-9][0-9]*$", getattr(node, "node_key", "")))


def scope_identity(node, content):
    return (node.node_type, node.target_object_id,
            tuple(sorted(content.get('knowledge_point_ids') or [])), content.get('teaching_unit_key'),
            (node.node_key, content.get('teaching_goal')) if is_staged_node(node) else None)


def path_node_scope(session, node):
    return tuple(path_node_content(session, node).get('knowledge_point_ids') or ())

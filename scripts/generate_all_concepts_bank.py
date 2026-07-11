import asyncio
import json
import os
import re
import sqlite3
import sys

# 将当前目录加入 path 以便于导入
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_client import DEFAULT_ASYNC_LLM
from agent_swarm import DEFAULT_KNOWLEDGE_DAG

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "edumatrix.db")

# 所有需要出题的知识点列表
CONCEPTS = list(DEFAULT_KNOWLEDGE_DAG.keys())
DIFFICULTIES = ["easy", "medium", "hard"]

async def generate_single_quiz(concept: str, difficulty: str, semaphore: asyncio.Semaphore) -> dict | None:
    async with semaphore:
        system_prompt = (
            "你是一个自适应评测题库生成专家。请针对给定的知识点和难度，生成一道高质量的多项选择题（四选一）。\n"
            "你必须且只能以 JSON 格式输出，不要有任何 Markdown ```json 标记或多余的解释。JSON 格式如下：\n"
            "{\n"
            '  "question": "题目文本",\n'
            '  "options": ["A. 选项A内容", "B. 选项B内容", "C. 选项C内容", "D. 选项D内容"],\n'
            '  "correct_answer": "正确选项(A/B/C/D之一)",\n'
            '  "explanation": "详细的原理解释"\n'
            "}"
        )
        user_prompt = f"知识点：{concept}\n难度：{difficulty} (对应 easy/medium/hard)"
        
        print(f"正在为知识点 [{concept}] 生成 [{difficulty}] 难度题目...")
        for attempt in range(3):  # 失败重试 3 次
            try:
                response = await DEFAULT_ASYNC_LLM.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    role="题库生成智能体"
                )
                # 清洗 JSON 标记
                raw_json = response.strip()
                if raw_json.startswith("```"):
                    raw_json = re.sub(r"^```[a-zA-Z0-9]*\n", "", raw_json)
                    raw_json = re.sub(r"\n```$", "", raw_json)
                raw_json = raw_json.strip()
                
                data = json.loads(raw_json)
                
                # 校验字段
                if "question" in data and "options" in data and "correct_answer" in data:
                    data["concept"] = concept
                    data["difficulty"] = difficulty
                    # 分配标准 3PL IRT 参数
                    data["irt_alpha"] = 1.0 + (0.2 if difficulty == "hard" else -0.1 if difficulty == "easy" else 0.0)
                    data["irt_beta"] = -1.0 if difficulty == "easy" else 1.0 if difficulty == "hard" else 0.0
                    data["irt_gamma"] = 0.25
                    return data
            except Exception as e:
                print(f"  [警告] 生成 [{concept}] ({difficulty}) 失败 (第 {attempt+1} 次): {e}")
                await asyncio.sleep(1.0)
        return None

async def main():
    print(f"=== EduMatrix 全量题库自动冷启动生成器 ===")
    print(f"发现知识大纲概念共 {len(CONCEPTS)} 个。")
    print(f"每个概念将生成 3 道题（Easy, Medium, Hard），共计 {len(CONCEPTS) * 3} 道题目。")
    
    # 限制并发请求量为 5，防止 API Rate Limit 报错
    semaphore = asyncio.Semaphore(5)
    
    tasks = []
    for concept in CONCEPTS:
        for diff in DIFFICULTIES:
            tasks.append(generate_single_quiz(concept, diff, semaphore))
            
    results = await asyncio.gather(*tasks)
    valid_quizzes = [r for r in results if r is not None]
    
    print(f"\n生成结束：计划生成 {len(tasks)} 道题，成功生成 {len(valid_quizzes)} 道题。")
    
    # 写入 SQLite 数据库
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 创建表（若不存在）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_items (
            id VARCHAR(64) PRIMARY KEY,
            concept VARCHAR(128),
            question TEXT NOT NULL,
            options TEXT DEFAULT '[]',
            correct_answer TEXT DEFAULT '',
            explanation TEXT DEFAULT '',
            difficulty VARCHAR(32) DEFAULT 'medium',
            irt_alpha FLOAT DEFAULT 1.0,
            irt_beta FLOAT DEFAULT 0.0,
            irt_gamma FLOAT DEFAULT 0.25,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    
    # 写入数据
    inserted = 0
    for i, q in enumerate(valid_quizzes):
        item_id = f"item_gen_{concept_to_slug(q['concept'])}_{q['difficulty']}_{i}"
        options_json = json.dumps(q["options"], ensure_ascii=False)
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO quiz_items (id, concept, question, options, correct_answer, explanation, difficulty, irt_alpha, irt_beta, irt_gamma)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item_id, q["concept"], q["question"], options_json, 
                q["correct_answer"], q.get("explanation", ""), q["difficulty"],
                q["irt_alpha"], q["irt_beta"], q["irt_gamma"]
            ))
            inserted += 1
        except Exception as e:
            print(f"写入题库失败: {e}")
            
    conn.commit()
    conn.close()
    print(f"=== 写入数据库完毕：共写入/更新 {inserted} 道题目到预置题库！ ===")

def concept_to_slug(concept: str) -> str:
    # 简单拼音或英文转换，此处为了生成 ID 可靠，直接采用哈希或编码
    return str(abs(hash(concept)) % 100000)

if __name__ == "__main__":
    # 执行异步主函数
    asyncio.run(main())

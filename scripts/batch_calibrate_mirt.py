#!/usr/bin/env python3
"""
scripts/batch_calibrate_mirt.py
EduMatrix 智教矩阵系统 - 离线 MIRT 题目参数批处理校准脚本。
作为 Cron 任务或手动运维脚本运行，避免在线高频 MCMC 计算引发 SQLite 锁和参数漂移。
"""

import sys
import os
import argparse

# 将项目根目录添加到 python 搜索路径中
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, DBQuizItem, DBQuizRecord, DBStudentProfile
from mirt_engine import mcmc_calibrate_item_parameters, IRTItemParams


def run_batch_calibration(iterations: int = 5000, burn_in: int = 1000, force: bool = False):
    print(f"=== [MIRT Batch Calibration] Starting calibration (iterations={iterations}, burn_in={burn_in}) ===")
    session = SessionLocal()
    try:
        # 1. 查找所有参与过测验的学生画像，获取其估计的 theta
        students = session.query(DBStudentProfile).filter(DBStudentProfile.rl_q_table.isnot(None)).all()
        student_list = []
        student_abilities = []
        for s in students:
            irt_est = s.rl_q_table.get("_irt_estimator", {})
            theta = irt_est.get("theta")
            if theta and isinstance(theta, list) and len(theta) == 3:
                student_list.append(s.student_id)
                student_abilities.append(theta)

        print(f"  Found {len(student_list)} students with valid 3D theta estimations.")

        # 2. 硬性阈值校验：至少需要 5 位学生才能启动校准，防止极小样本引起参数剧烈漂移
        MIN_STUDENTS = 5
        if len(student_list) < MIN_STUDENTS and not force:
            print(f"  [Abort] Sample size ({len(student_list)}) is below minimum threshold ({MIN_STUDENTS}).")
            print("  MCMC parameter calibration will not run to prevent parameter drift. Exit.")
            return

        # 3. 查找所有的本地种子题目
        items = session.query(DBQuizItem).all()
        if not items:
            print("  [Abort] No quiz items found in database. Exit.")
            return

        print(f"  Found {len(items)} quiz items in database. Commencing response matrix mapping...")
        item_ids = [item.id for item in items]
        initial_items = []
        for item in items:
            alpha = item.irt_alpha_vec if item.irt_alpha_vec is not None else item.irt_alpha
            beta = item.irt_beta_vec if item.irt_beta_vec is not None else item.irt_beta
            initial_items.append(IRTItemParams.from_dict({
                "alpha": alpha,
                "beta": beta,
                "gamma": item.irt_gamma
            }))

        # 4. 构造答题矩阵 (N_students, M_items)
        response_matrix = [[0] * len(item_ids) for _ in range(len(student_list))]
        student_idx_map = {sid: idx for idx, sid in enumerate(student_list)}
        item_idx_map = {iid: idx for idx, iid in enumerate(item_ids)}

        records = session.query(DBQuizRecord).filter(
            DBQuizRecord.student_id.in_(student_list)
        ).all()

        mapped_count = 0
        for r in records:
            # 匹配对应的问题
            item_match = next((item for item in items if item.question == r.question), None)
            if item_match:
                s_idx = student_idx_map.get(r.student_id)
                i_idx = item_idx_map.get(item_match.id)
                if s_idx is not None and i_idx is not None:
                    response_matrix[s_idx][i_idx] = 1 if (r.accuracy_score >= 0.6) else 0
                    mapped_count += 1

        print(f"  Mapped {mapped_count} user response records to the matrix ({len(student_list)}x{len(item_ids)}).")

        # 5. 执行 MCMC 校准
        print(f"  Running Metropolis-Hastings MCMC parameter estimation (this may take a few seconds)...")
        calibrated = mcmc_calibrate_item_parameters(
            response_matrix=response_matrix,
            student_abilities=student_abilities,
            initial_items=initial_items,
            iterations=iterations,
            burn_in=burn_in
        )

        # 6. 将校准后的参数更新写回数据库 (DBQuizItem & DBQuizRecord)
        print("  MCMC estimation completed. Committing calibrated parameters to database...")
        for idx, item_id in enumerate(item_ids):
            c_item = calibrated[idx]
            # 更新种子题库参数
            session.query(DBQuizItem).filter(DBQuizItem.id == item_id).update({
                "irt_alpha_vec": c_item.alpha,
                "irt_beta_vec": c_item.beta,
                "irt_alpha": c_item.alpha[0],
                "irt_beta": c_item.beta[0],
            }, synchronize_session=False)
            
            # 同时更新对应的答题历史快照参数，保证模型分析一致性
            item_match = items[idx]
            session.query(DBQuizRecord).filter(DBQuizRecord.question == item_match.question).update({
                "irt_alpha_vec": c_item.alpha,
                "irt_beta_vec": c_item.beta,
                "irt_alpha": c_item.alpha[0],
                "irt_beta": c_item.beta[0],
            }, synchronize_session=False)

        session.commit()
        print(f"[SUCCESS] [MIRT Batch Calibration] Success! Calibrated parameters for {len(item_ids)} items.")

    except Exception as e:
        session.rollback()
        print(f"[ERROR] [MIRT Batch Calibration] Failed: {e}", file=sys.stderr)
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MIRT Item Parameter Calibration Script")
    parser.add_argument("--iterations", type=int, default=5000, help="MCMC iteration steps")
    parser.add_argument("--burn-in", type=int, default=1000, help="MCMC burn-in iterations")
    parser.add_argument("--force", action="store_true", help="Force calibration even with <5 students")
    args = parser.parse_args()

    run_batch_calibration(iterations=args.iterations, burn_in=args.burn_in, force=args.force)

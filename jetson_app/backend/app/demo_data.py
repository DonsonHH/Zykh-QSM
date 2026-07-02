from __future__ import annotations

from .db import connect, init_db, now_text


DEMO_MEDICINES = [
    (1, "阿司匹林肠溶片", "100mg/片", 12, "2026-12-31", "869000100001", "big", "慢病常用", "高血压随访,按计划服药", "活动性出血、阿司匹林过敏禁用", "按既有医嘱服用", "慢病处方药，仅用于既有计划提醒", "片", 0, 1),
    (2, "维生素C片", "100mg/片", 30, "2027-03-31", "869000100002", "big", "其他应急", "营养补充", "肾结石风险者需咨询医生", "按说明书核对", "非紧急药品，不替代治疗", "片", 1, 0),
    (3, "布洛芬缓释胶囊", "200mg/粒", 8, "2026-08-30", "869000100003", "big", "感冒发热", "发热,疼痛", "胃溃疡、肾病、NSAID过敏禁用", "按说明书和管理员核验", "发热高风险或儿童老人需人工复核", "粒", 1, 0),
    (4, "连花清瘟胶囊", "0.35g*24粒", 15, "2026-12-31", "869000100004", "big", "感冒发热", "咽痛,流涕,感冒", "孕妇、过敏体质需咨询医生", "按说明书核对", "仅作为候选药品展示，需人工核验", "盒", 1, 0),
    (5, "板蓝根颗粒", "10g/袋", 20, "2027-01-31", "869000100005", "big", "感冒发热", "咽痛,感冒初期", "糖尿病患者注意含糖制剂", "按说明书冲服", "症状加重需联系医生", "袋", 1, 0),
    (7, "硝苯地平控释片", "30mg/片", 10, "2026-11-30", "869000100007", "big", "慢病常用", "高血压,每日计划", "低血压或过敏禁用", "按既有医嘱服用", "不可自行加量或停药", "片", 0, 1),
    (9, "口服补液盐", "5.125g/袋", 20, "2027-05-31", "869000100009", "small", "肠胃", "腹泻,脱水风险", "严重肾病或无法进食需医生处理", "按说明书兑水", "老人儿童脱水需人工复核", "袋", 1, 0),
    (10, "碘伏棉签", "10支/盒", 16, "2027-02-28", "869000100010", "small", "外伤消毒", "擦伤,外伤消毒", "碘过敏慎用", "外用，勿入口", "深伤口或大出血需救援", "盒", 1, 0),
]

DEMO_PLANS = [
    (1, "08:00", "1片"),
    (7, "18:30", "1片"),
    (4, "20:00", "1盒"),
]

DEMO_RECORDS = [
    ("dispense", 7, "硝苯地平控释片", "success", "18:30 已按计划取药"),
    ("vitals_read", 0, "体征测量", "success", "心率72，血氧98%，体温36.5℃"),
    ("medicine_scan", 4, "连花清瘟胶囊", "success", "识别置信度98%，已建议录入04号仓"),
    ("ai_chat", 0, "AI问诊", "success", "已生成高血压用药注意事项"),
]


def seed_demo_data() -> None:
    init_db()
    now = now_text()
    with connect() as conn:
        conn.execute(
            """
            UPDATE site_profile
            SET station_name=?, station_type=?, location_name=?, altitude=?, environment_tags=?,
                network_mode=?, ai_mode=?, emergency_contact=?, manager_name=?,
                last_sync_at=?, pending_sync_count=?, sync_status=?, updated_at=?
            WHERE id=1
            """,
            (
                "偏远社区康护站",
                "village",
                "村镇智慧用药服务点",
                780,
                "弱网,村镇,老人慢病,应急药品供给,管理员复核",
                "weak",
                "local",
                "村医 138****1200 / 镇卫生院",
                "王管理员",
                "2026-07-02 09:30:00",
                3,
                "待同步",
                now,
            ),
        )

        conn.execute(
            """
            UPDATE profile
            SET name=?, gender=?, age=?, height=?, weight=?, conditions=?,
                allergies=?, notes=?, updated_at=?
            WHERE id=1
            """,
            (
                "张三",
                "男",
                65,
                "170",
                "68",
                "高血压；糖尿病前期",
                "青霉素",
                "需饭后服药，家属关注夜间漏服情况。",
                now,
            ),
        )

        for slot in range(1, 24):
            conn.execute(
                """
                UPDATE medicines
                SET name='', dosage='', stock=0, expire_date='', code='',
                    trace_code='', box_size=box_size, category='其他应急',
                    indication_tags='', contraindications='', dosage_note='',
                    safety_note='', unit='件', barcode='', image_path='',
                    is_emergency=1, is_daily_plan_medicine=0, updated_at=?
                WHERE slot=?
                """,
                (now, slot),
            )

        for slot, name, dosage, stock, expire_date, code, box_size, category, tags, contraindications, dosage_note, safety_note, unit, is_emergency, is_daily in DEMO_MEDICINES:
            conn.execute(
                """
                UPDATE medicines
                SET name=?, dosage=?, stock=?, expire_date=?, code=?,
                    trace_code=?, box_size=?, category=?, indication_tags=?,
                    contraindications=?, dosage_note=?, safety_note=?, unit=?,
                    barcode=?, is_emergency=?, is_daily_plan_medicine=?, updated_at=?
                WHERE slot=?
                """,
                (
                    name,
                    dosage,
                    stock,
                    expire_date,
                    code,
                    f"TRACE-DEMO-{slot:02d}",
                    box_size,
                    category,
                    tags,
                    contraindications,
                    dosage_note,
                    safety_note,
                    unit,
                    code,
                    is_emergency,
                    is_daily,
                    now,
                    slot,
                ),
            )

        conn.execute("DELETE FROM plans")
        for slot, time_text, amount in DEMO_PLANS:
            conn.execute(
                "INSERT INTO plans(slot,time,amount,enabled,created_at) VALUES (?,?,?,?,?)",
                (slot, time_text, amount, 1, now),
            )

        conn.execute("DELETE FROM vitals_records")
        conn.execute(
            """
            INSERT INTO vitals_records
            (temperature, heart_rate, spo2, systolic, diastolic, source, quality, created_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (36.5, 72, 98, 128, 78, "demo", "good", now),
        )

        conn.execute("DELETE FROM records")
        for action, slot, subject, result, detail in DEMO_RECORDS:
            conn.execute(
                "INSERT INTO records(action, slot, subject, result, detail, created_at) VALUES (?,?,?,?,?,?)",
                (action, slot, subject, result, detail, now),
            )

        conn.execute("DELETE FROM emergency_sessions")
        conn.execute(
            """
            INSERT INTO emergency_sessions(started_at,scene_type,network_mode,symptoms_text,
              vitals_snapshot,allergy_or_contraindication,current_medicine_context,ai_mode,
              risk_level,symptoms_summary,suggested_categories,candidate_medicines,
              safety_warnings,next_steps,need_admin_review,allow_self_confirm,action_summary,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                now,
                "village",
                "weak",
                "村民轻微咽痛流涕，想确认服务点是否有可用药品",
                "{}",
                "无已知过敏",
                "感冒发热类库存可用",
                "rules",
                "low",
                "轻微上呼吸道不适",
                '["感冒发热"]',
                '[{"slot":4,"name":"连花清瘟胶囊","stock":15}]',
                '["请核对说明书、过敏史和重复用药。"]',
                '["低风险可进入用户取药确认，仍需管理员抽查。"]',
                0,
                1,
                "低风险可进入取药确认",
                now,
            ),
        )

        conn.execute("DELETE FROM dispense_records")
        conn.execute(
            """
            INSERT INTO dispense_records(session_id,slot,medicine_name,quantity,reason,
              confirmed_by_user,admin_reviewed,dry_run,success,detail,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (1, 4, "连花清瘟胶囊", 1, "低风险应急问询取药确认", 1, 0, 1, 1, "dry-run 演示记录，未触发真实开仓", now),
        )

        conn.execute("DELETE FROM network_events")
        conn.execute(
            "INSERT INTO network_events(mode,ai_mode,reason,created_at) VALUES (?,?,?,?)",
            ("weak", "local", "村镇弱网模式演示，云端超时后切换本地模型/rules", now),
        )

        conn.execute("DELETE FROM operator_logs")
        conn.execute(
            "INSERT INTO operator_logs(operator,action,target_type,target_id,detail,created_at) VALUES (?,?,?,?,?,?)",
            ("王管理员", "admin_review", "emergency_session", "1", "已复核低风险应急问询演示记录", now),
        )

        conn.execute("DELETE FROM health_memories")
        conn.execute(
            """
            INSERT INTO health_memories(type,title,content,happened_at,source,created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                "condition",
                "慢病管理",
                "长期高血压，需关注按时服药、低盐饮食和每日体征测量。",
                now,
                "demo",
                now,
            ),
        )


def clear_demo_data() -> None:
    init_db()
    now = now_text()
    with connect() as conn:
        conn.execute(
            """
            UPDATE profile
            SET name='', gender='', age=0, height='', weight='', conditions='',
                allergies='', notes='', updated_at=?
            WHERE id=1
            """,
            (now,),
        )
        for slot in range(1, 24):
            conn.execute(
                """
                UPDATE medicines
                SET name='', dosage='', stock=0, expire_date='', code='',
                    trace_code='', box_size=box_size, category='其他应急',
                    indication_tags='', contraindications='', dosage_note='',
                    safety_note='', unit='件', barcode='', image_path='',
                    is_emergency=1, is_daily_plan_medicine=0, updated_at=?
                WHERE slot=?
                """,
                (now, slot),
            )
        conn.execute("DELETE FROM plans")
        conn.execute("DELETE FROM records")
        conn.execute("DELETE FROM vitals_records")
        conn.execute("DELETE FROM health_memories")
        conn.execute("DELETE FROM emergency_sessions")
        conn.execute("DELETE FROM dispense_records")
        conn.execute("DELETE FROM network_events")
        conn.execute("DELETE FROM operator_logs")


if __name__ == "__main__":
    seed_demo_data()
    print("Demo data seeded.")

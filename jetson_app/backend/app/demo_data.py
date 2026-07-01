from __future__ import annotations

from .db import connect, init_db, now_text


DEMO_MEDICINES = [
    (1, "阿司匹林肠溶片", "100mg/片", 12, "2026-12-31", "869000100001", "big"),
    (2, "维生素C片", "100mg/片", 30, "2027-03-31", "869000100002", "big"),
    (3, "布洛芬缓释胶囊", "200mg/粒", 8, "2026-08-30", "869000100003", "big"),
    (4, "连花清瘟胶囊", "0.35g*24粒", 15, "2026-12-31", "869000100004", "big"),
    (5, "板蓝根颗粒", "10g/袋", 20, "2027-01-31", "869000100005", "big"),
    (7, "硝苯地平控释片", "30mg/片", 10, "2026-11-30", "869000100007", "big"),
    (9, "鱼油软胶囊", "1000mg/粒", 20, "2027-05-31", "869000100009", "small"),
    (10, "维生素D滴剂", "400IU/粒", 16, "2027-02-28", "869000100010", "small"),
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
                    trace_code='', box_size=box_size, updated_at=?
                WHERE slot=?
                """,
                (now, slot),
            )

        for slot, name, dosage, stock, expire_date, code, box_size in DEMO_MEDICINES:
            conn.execute(
                """
                UPDATE medicines
                SET name=?, dosage=?, stock=?, expire_date=?, code=?,
                    trace_code=?, box_size=?, updated_at=?
                WHERE slot=?
                """,
                (name, dosage, stock, expire_date, code, f"TRACE-DEMO-{slot:02d}", box_size, now, slot),
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
                    trace_code='', box_size=box_size, updated_at=?
                WHERE slot=?
                """,
                (now, slot),
            )
        conn.execute("DELETE FROM plans")
        conn.execute("DELETE FROM records")
        conn.execute("DELETE FROM vitals_records")
        conn.execute("DELETE FROM health_memories")


if __name__ == "__main__":
    seed_demo_data()
    print("Demo data seeded.")

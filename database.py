import sqlite3
import time

from pathlib import Path


# ============================================================
# Database Path
#
# 使用 app 所在目錄的絕對路徑。
#
# 這樣未來用 systemd 啟動時，
# 不會因為 working directory 不同，
# 結果產生另一個 monitor.db。
# ============================================================

BASE_DIR = Path(
    __file__
).resolve().parent


DB_FILE = (
    BASE_DIR
    /
    "monitor.db"
)


# ============================================================
# Retention
# ============================================================

TRAFFIC_RETENTION_DAYS = 7

EVENT_RETENTION_DAYS = 30

ALERT_RETENTION_DAYS = 90


# ============================================================
# 建立 Database Connection
# ============================================================

def get_connection():

    return sqlite3.connect(
        DB_FILE,
        timeout=10
    )


# ============================================================
# 初始化 Database
# ============================================================

def init_db():

    conn = get_connection()

    cursor = conn.cursor()


    # ========================================================
    # Traffic History
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS interface_history
        (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp REAL NOT NULL,

            interface_index INTEGER NOT NULL,

            interface_name TEXT NOT NULL,

            rx_mbps REAL NOT NULL,

            tx_mbps REAL NOT NULL
        )
        """
    )


    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_interface_history_interface_time

        ON interface_history
        (
            interface_index,
            timestamp
        )
        """
    )


    # ========================================================
    # Events
    #
    # Event = 發生過什麼變化
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS events
        (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp REAL NOT NULL,

            interface_index INTEGER NOT NULL,

            interface_name TEXT NOT NULL,

            event_type TEXT NOT NULL,

            old_status TEXT NOT NULL,

            new_status TEXT NOT NULL
        )
        """
    )


    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_events_timestamp

        ON events
        (
            timestamp
        )
        """
    )


    # ========================================================
    # Alerts
    #
    # active:
    #     1 = 問題還存在
    #     0 = 問題已恢復
    # ========================================================

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts
        (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            created_at REAL NOT NULL,

            resolved_at REAL,

            interface_index INTEGER NOT NULL,

            interface_name TEXT NOT NULL,

            alert_type TEXT NOT NULL,

            severity TEXT NOT NULL,

            description TEXT,

            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )


    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_alerts_active_time

        ON alerts
        (
            active,
            created_at
        )
        """
    )


    conn.commit()

    conn.close()


# ============================================================
# Traffic History
# ============================================================

def save_interface_history(
    timestamp,
    interfaces
):

    if not interfaces:
        return


    conn = get_connection()

    cursor = conn.cursor()


    rows = []


    for interface in interfaces:

        rows.append(
            (
                timestamp,

                interface["index"],

                interface["name"],

                interface["rx_mbps"],

                interface["tx_mbps"]
            )
        )


    cursor.executemany(
        """
        INSERT INTO interface_history
        (
            timestamp,
            interface_index,
            interface_name,
            rx_mbps,
            tx_mbps
        )

        VALUES (?, ?, ?, ?, ?)
        """,
        rows
    )


    conn.commit()

    conn.close()


# ============================================================
# 取得 Traffic History
# ============================================================

def get_interface_history(
    interface_index,
    seconds=3600
):

    since_timestamp = (
        time.time()
        -
        seconds
    )


    conn = get_connection()

    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT
            timestamp,
            rx_mbps,
            tx_mbps

        FROM interface_history

        WHERE
            interface_index = ?
            AND timestamp >= ?

        ORDER BY timestamp ASC
        """,
        (
            interface_index,
            since_timestamp
        )
    )


    rows = cursor.fetchall()

    conn.close()


    return [
        {
            "timestamp":
                row[0],

            "rx_mbps":
                row[1],

            "tx_mbps":
                row[2]
        }

        for row in rows
    ]


# ============================================================
# Events
# ============================================================

def save_event(
    timestamp,
    interface_index,
    interface_name,
    event_type,
    old_status,
    new_status
):

    conn = get_connection()

    cursor = conn.cursor()


    cursor.execute(
        """
        INSERT INTO events
        (
            timestamp,
            interface_index,
            interface_name,
            event_type,
            old_status,
            new_status
        )

        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp,
            interface_index,
            interface_name,
            event_type,
            old_status,
            new_status
        )
    )


    conn.commit()

    conn.close()


# ============================================================
# 最近 Events
# ============================================================

def get_recent_events(
    limit=50
):

    limit = max(
        1,
        min(
            int(limit),
            500
        )
    )


    conn = get_connection()

    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT
            id,
            timestamp,
            interface_index,
            interface_name,
            event_type,
            old_status,
            new_status

        FROM events

        ORDER BY timestamp DESC

        LIMIT ?
        """,
        (
            limit,
        )
    )


    rows = cursor.fetchall()

    conn.close()


    return [
        {
            "id":
                row[0],

            "timestamp":
                row[1],

            "interface_index":
                row[2],

            "interface_name":
                row[3],

            "event_type":
                row[4],

            "old_status":
                row[5],

            "new_status":
                row[6]
        }

        for row in rows
    ]


# ============================================================
# 建立 Alert
# ============================================================

def create_alert(
    timestamp,
    interface_index,
    interface_name,
    alert_type,
    severity,
    description
):

    conn = get_connection()

    cursor = conn.cursor()


    # ========================================================
    # 防止重複 Active Alert
    #
    # 同一個 interface + alert_type
    # 已經 Active 時，不建立第二筆。
    # ========================================================

    cursor.execute(
        """
        SELECT id

        FROM alerts

        WHERE
            interface_index = ?
            AND alert_type = ?
            AND active = 1

        LIMIT 1
        """,
        (
            interface_index,
            alert_type
        )
    )


    existing = (
        cursor.fetchone()
    )


    if existing:

        conn.close()

        return False


    cursor.execute(
        """
        INSERT INTO alerts
        (
            created_at,
            resolved_at,

            interface_index,
            interface_name,

            alert_type,
            severity,
            description,

            active
        )

        VALUES
        (
            ?,
            NULL,

            ?,
            ?,

            ?,
            ?,
            ?,

            1
        )
        """,
        (
            timestamp,

            interface_index,
            interface_name,

            alert_type,
            severity,
            description
        )
    )


    conn.commit()

    conn.close()


    return True


# ============================================================
# Resolve Alert
# ============================================================

def resolve_interface_alert(
    timestamp,
    interface_index,
    alert_type
):

    conn = get_connection()

    cursor = conn.cursor()


    cursor.execute(
        """
        UPDATE alerts

        SET
            active = 0,
            resolved_at = ?

        WHERE
            interface_index = ?
            AND alert_type = ?
            AND active = 1
        """,
        (
            timestamp,
            interface_index,
            alert_type
        )
    )


    resolved_count = (
        cursor.rowcount
    )


    conn.commit()

    conn.close()


    return resolved_count


# ============================================================
# Active Alerts
# ============================================================

def get_active_alerts():

    conn = get_connection()

    cursor = conn.cursor()


    # SQL 這裡直接先按 Severity 排序
    cursor.execute(
        """
        SELECT
            id,
            created_at,

            interface_index,
            interface_name,

            alert_type,
            severity,
            description

        FROM alerts

        WHERE active = 1

        ORDER BY
            CASE severity

                WHEN 'CRITICAL'
                    THEN 1

                WHEN 'WARNING'
                    THEN 2

                ELSE 3

            END ASC,

            created_at ASC
        """
    )


    rows = cursor.fetchall()

    conn.close()


    return [
        {
            "id":
                row[0],

            "created_at":
                row[1],

            "interface_index":
                row[2],

            "interface_name":
                row[3],

            "alert_type":
                row[4],

            "severity":
                row[5],

            "description":
                row[6]
        }

        for row in rows
    ]


# ============================================================
# Recent Alerts
# ============================================================

def get_recent_alerts(
    limit=50
):

    limit = max(
        1,
        min(
            int(limit),
            500
        )
    )


    conn = get_connection()

    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT
            id,
            created_at,
            resolved_at,

            interface_index,
            interface_name,

            alert_type,
            severity,
            description,

            active

        FROM alerts

        ORDER BY created_at DESC

        LIMIT ?
        """,
        (
            limit,
        )
    )


    rows = cursor.fetchall()

    conn.close()


    return [
        {
            "id":
                row[0],

            "created_at":
                row[1],

            "resolved_at":
                row[2],

            "interface_index":
                row[3],

            "interface_name":
                row[4],

            "alert_type":
                row[5],

            "severity":
                row[6],

            "description":
                row[7],

            "active":
                bool(
                    row[8]
                )
        }

        for row in rows
    ]


# ============================================================
# 清除舊資料
# ============================================================

def cleanup_old_data():

    now = (
        time.time()
    )


    traffic_cutoff = (
        now
        -
        TRAFFIC_RETENTION_DAYS
        * 24
        * 60
        * 60
    )


    event_cutoff = (
        now
        -
        EVENT_RETENTION_DAYS
        * 24
        * 60
        * 60
    )


    alert_cutoff = (
        now
        -
        ALERT_RETENTION_DAYS
        * 24
        * 60
        * 60
    )


    conn = get_connection()

    cursor = conn.cursor()


    # Traffic
    cursor.execute(
        """
        DELETE FROM interface_history

        WHERE timestamp < ?
        """,
        (
            traffic_cutoff,
        )
    )

    traffic_deleted = (
        cursor.rowcount
    )


    # Events
    cursor.execute(
        """
        DELETE FROM events

        WHERE timestamp < ?
        """,
        (
            event_cutoff,
        )
    )

    events_deleted = (
        cursor.rowcount
    )


    # 只刪已經 resolved 的 Alert
    #
    # Active Alert 永遠不能因為 retention 被刪掉。
    cursor.execute(
        """
        DELETE FROM alerts

        WHERE
            active = 0
            AND resolved_at IS NOT NULL
            AND resolved_at < ?
        """,
        (
            alert_cutoff,
        )
    )

    alerts_deleted = (
        cursor.rowcount
    )


    conn.commit()

    conn.close()


    return {
        "traffic_deleted":
            traffic_deleted,

        "events_deleted":
            events_deleted,

        "alerts_deleted":
            alerts_deleted
    }


# ============================================================
# Database Status
# ============================================================

def get_database_status():

    conn = get_connection()

    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT COUNT(*)
        FROM interface_history
        """
    )

    history_rows = (
        cursor.fetchone()[0]
    )


    cursor.execute(
        """
        SELECT COUNT(*)
        FROM events
        """
    )

    event_rows = (
        cursor.fetchone()[0]
    )


    cursor.execute(
        """
        SELECT COUNT(*)
        FROM alerts
        """
    )

    alert_rows = (
        cursor.fetchone()[0]
    )


    cursor.execute(
        """
        SELECT COUNT(*)

        FROM alerts

        WHERE active = 1
        """
    )

    active_alerts = (
        cursor.fetchone()[0]
    )


    conn.close()


    return {
        "database":
            str(
                DB_FILE
            ),

        "history_rows":
            history_rows,

        "event_rows":
            event_rows,

        "alert_rows":
            alert_rows,

        "active_alerts":
            active_alerts,

        "traffic_retention_days":
            TRAFFIC_RETENTION_DAYS,

        "event_retention_days":
            EVENT_RETENTION_DAYS,

        "alert_retention_days":
            ALERT_RETENTION_DAYS
    }

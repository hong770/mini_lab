import sqlite3
import time


DB_FILE = "monitor.db"

# 歷史資料只保留 7 天
RETENTION_DAYS = 7


# ============================================================
# 建立資料庫
# ============================================================

def init_db():

    conn = sqlite3.connect(
        DB_FILE
    )

    cursor = conn.cursor()


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


    # --------------------------------------------------------
    # 建 Index
    #
    # 之後查：
    #
    # WHERE interface_index = ?
    # ORDER BY timestamp
    #
    # 會快很多
    # --------------------------------------------------------

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


    conn.commit()

    conn.close()


# ============================================================
# 儲存 Interface History
# ============================================================

def save_interface_history(
    timestamp,
    interfaces
):

    if not interfaces:
        return


    conn = sqlite3.connect(
        DB_FILE
    )

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

        VALUES
        (
            ?,
            ?,
            ?,
            ?,
            ?
        )
        """,
        rows
    )


    conn.commit()

    conn.close()


# ============================================================
# 取得 Interface 歷史
# ============================================================

def get_interface_history(
    interface_index,
    seconds=3600
):

    # 預設只抓最近 1 小時
    since_timestamp = (
        time.time()
        - seconds
    )


    conn = sqlite3.connect(
        DB_FILE
    )

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
# 清除超過保留期限的資料
# ============================================================

def cleanup_old_history():

    cutoff = (
        time.time()
        -
        RETENTION_DAYS
        * 24
        * 60
        * 60
    )


    conn = sqlite3.connect(
        DB_FILE
    )

    cursor = conn.cursor()


    cursor.execute(
        """
        DELETE FROM interface_history

        WHERE timestamp < ?
        """,
        (
            cutoff,
        )
    )


    deleted_rows = (
        cursor.rowcount
    )


    conn.commit()

    conn.close()


    print(
        f"Database cleanup: "
        f"{deleted_rows} old rows removed"
    )


# ============================================================
# Database Status
# ============================================================

def get_database_status():

    conn = sqlite3.connect(
        DB_FILE
    )

    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT COUNT(*)
        FROM interface_history
        """
    )


    row_count = (
        cursor.fetchone()[0]
    )


    conn.close()


    return {
        "rows":
            row_count,

        "retention_days":
            RETENTION_DAYS
    }

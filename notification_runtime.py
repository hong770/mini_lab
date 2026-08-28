import time

from collections import deque


from notification_engine import (
    NotificationEngine
)


# ============================================================
# Notification Engine Instance
#
# 整個 FastAPI Process 共用同一顆 Engine。
#
# 正式環境設定：
#
# cooldown:
#     同一 notification type 5 分鐘不重複通知
#
# flap window:
#     120 秒內觀察 Port transition
#
# flap threshold:
#     4 次 transition 判定 flapping
#
# flap clear:
#     180 秒完全沒變化才判定恢復穩定
# ============================================================

notification_engine = NotificationEngine(

    cooldown_seconds=300,

    flap_window_seconds=120,

    flap_threshold=4,

    flap_clear_seconds=180
)


# ============================================================
# Runtime State
# ============================================================

# ------------------------------------------------------------
# 記住上一輪每個 interface 的 operational status
#
# key:
#
#     192.168.10.2:10101
#
# value:
#
#     "up"
#     "down"
#
# 注意：
#
# 這跟 Alert v2 自己的 previous state 完全分離。
#
# Notification Engine 暫時不侵入 Alert v2。
# ------------------------------------------------------------

previous_oper_status = {}


# ------------------------------------------------------------
# Runtime 是否已建立第一輪 baseline
#
# FastAPI 剛啟動：
#
# 48 個 Port 本來就有 up/down 狀態
#
# 那不是「事件」。
#
# 所以第一輪只記錄 baseline，
# 不產生 LINK_UP / LINK_DOWN。
# ------------------------------------------------------------

baseline_initialized = False


# ------------------------------------------------------------
# 最近的 Notification Decisions
#
# 包含：
#
# SEND
# SUPPRESS
#
# 保留最近 200 筆在 RAM。
#
# 目前先不寫 DB。
#
# 下一階段接 Telegram / Email 時，
# SEND decision 就會進 Dispatcher。
# ------------------------------------------------------------

recent_decisions = deque(
    maxlen=200
)


# ============================================================
# Runtime Statistics
# ============================================================

runtime_stats = {

    "snapshots_processed": 0,

    "transitions_detected": 0,

    "send_decisions": 0,

    "suppressed_decisions": 0,

    "last_snapshot_at": None,

    "last_transition_at": None
}


# ============================================================
# Normalize Status
#
# Cisco IF-MIB:
#
# ifAdminStatus
# ifOperStatus
#
# 1 = up
# 2 = down
# 3 = testing
#
#
# snmp.py 未來不管回：
#
#     1
#     "1"
#     "up"
#     "UP"
#
# Runtime 都統一轉成：
#
#     "up"
#     "down"
#     "testing"
#     "unknown"
# ============================================================

def normalize_status(
    value
):

    if value is None:

        return "unknown"


    normalized = (
        str(value)
        .strip()
        .lower()
    )


    if normalized in (
        "1",
        "up"
    ):

        return "up"


    if normalized in (
        "2",
        "down"
    ):

        return "down"


    if normalized in (
        "3",
        "testing"
    ):

        return "testing"


    return normalized


# ============================================================
# Build Entity Key
# ============================================================

def make_entity_key(
    switch_ip,
    interface_index
):

    return (
        f"{switch_ip}:"
        f"{interface_index}"
    )


# ============================================================
# Store Decision
# ============================================================

def store_decision(
    decision
):

    decision_dict = (
        decision.to_dict()
    )


    recent_decisions.appendleft(
        decision_dict
    )


    action = (
        decision_dict.get(
            "action"
        )
    )


    if action == "SEND":

        runtime_stats[
            "send_decisions"
        ] += 1


    elif action == "SUPPRESS":

        runtime_stats[
            "suppressed_decisions"
        ] += 1


# ============================================================
# Get Switch Hostname
#
# basic_info 正常應該有：
#
# {
#     "hostname": "...",
#     "ip": "...",
#     ...
# }
#
# 但這裡仍然做 defensive fallback，
# 避免 SNMP 某欄位暫時缺失讓 Runtime crash。
# ============================================================

def get_switch_hostname(
    basic_info
):

    if not isinstance(
        basic_info,
        dict
    ):

        return "Unknown"


    return (

        basic_info.get(
            "hostname"
        )

        or basic_info.get(
            "name"
        )

        or "Unknown"
    )


# ============================================================
# Get Switch IP
# ============================================================

def get_switch_ip(
    basic_info
):

    if isinstance(
        basic_info,
        dict
    ):

        switch_ip = (
            basic_info.get(
                "ip"
            )
        )


        if switch_ip:

            return str(
                switch_ip
            )


    # --------------------------------------------------------
    # 現在 Lab Switch
    # --------------------------------------------------------

    return "192.168.10.2"


# ============================================================
# Build LINK Event
#
# 這裡是：
#
# SNMP Snapshot
#
#       ↓
#
# Notification Event
#
#
# Alert v2 不需要知道這個 Runtime 的存在。
# ============================================================

def build_link_event(
    event_type,
    timestamp,
    switch_name,
    switch_ip,
    interface
):

    interface_index = (
        interface.get(
            "index"
        )
    )


    interface_name = (

        interface.get(
            "name"
        )

        or f"ifIndex {interface_index}"
    )


    admin_status = (
        normalize_status(
            interface.get(
                "admin_status"
            )
        )
    )


    oper_status = (
        normalize_status(
            interface.get(
                "oper_status"
            )
        )
    )


    return {

        "event_type":
            event_type,

        "timestamp":
            timestamp,

        "switch_name":
            switch_name,

        "switch_ip":
            switch_ip,

        "interface_index":
            interface_index,

        "interface_name":
            interface_name,

        "admin_status":
            admin_status,

        "oper_status":
            oper_status
    }


# ============================================================
# Process Notification Snapshot
#
# 每輪 SNMP Poll 呼叫一次。
#
#
# 輸入：
#
# basic_info
#
# current_interfaces
#
# current_time
#
#
# current_interfaces 格式：
#
# {
#     ifIndex: {
#         "index": ...,
#         "name": ...,
#         "admin_status": ...,
#         "oper_status": ...
#     }
# }
#
#
# 輸出：
#
# [
#     NotificationDecision,
#     NotificationDecision,
#     ...
# ]
#
#
# 沒事件時：
#
# []
# ============================================================

def process_notification_snapshot(
    basic_info,
    current_interfaces,
    current_time=None
):

    global baseline_initialized


    # ========================================================
    # Timestamp
    # ========================================================

    if current_time is None:

        current_time = (
            time.time()
        )


    runtime_stats[
        "snapshots_processed"
    ] += 1


    runtime_stats[
        "last_snapshot_at"
    ] = current_time


    decisions = []


    # ========================================================
    # Defensive Check
    # ========================================================

    if not isinstance(
        current_interfaces,
        dict
    ):

        return decisions


    # ========================================================
    # Switch Identity
    # ========================================================

    switch_name = (
        get_switch_hostname(
            basic_info
        )
    )


    switch_ip = (
        get_switch_ip(
            basic_info
        )
    )


    # ========================================================
    # 第一輪：
    #
    # 只建立 baseline。
    #
    # 不發通知。
    # ========================================================

    if not baseline_initialized:

        for (
            interface_index,
            interface
        ) in current_interfaces.items():

            index = (
                interface.get(
                    "index",
                    interface_index
                )
            )


            oper_status = (
                normalize_status(
                    interface.get(
                        "oper_status"
                    )
                )
            )


            entity_key = (
                make_entity_key(
                    switch_ip,
                    index
                )
            )


            previous_oper_status[
                entity_key
            ] = oper_status


        baseline_initialized = True


        return decisions


    # ========================================================
    # Compare Current Snapshot
    # ========================================================

    for (
        interface_index,
        interface
    ) in current_interfaces.items():

        # ----------------------------------------------------
        # Interface Index
        # ----------------------------------------------------

        index = (
            interface.get(
                "index",
                interface_index
            )
        )


        # ----------------------------------------------------
        # Current Oper Status
        # ----------------------------------------------------

        current_status = (
            normalize_status(
                interface.get(
                    "oper_status"
                )
            )
        )


        # ----------------------------------------------------
        # Entity
        # ----------------------------------------------------

        entity_key = (
            make_entity_key(
                switch_ip,
                index
            )
        )


        # ----------------------------------------------------
        # Previous Oper Status
        # ----------------------------------------------------

        old_status = (
            previous_oper_status.get(
                entity_key
            )
        )


        # ----------------------------------------------------
        # Runtime 第一次看到這個 Port
        #
        # 例如：
        #
        # 新增 module
        # SNMP interface table 變化
        #
        # 一樣只建立 baseline。
        # ----------------------------------------------------

        if old_status is None:

            previous_oper_status[
                entity_key
            ] = current_status


            continue


        # ----------------------------------------------------
        # 狀態沒變
        #
        # 不叫 Notification Engine。
        #
        # 非常重要：
        #
        # poll 每 5 秒得到 "down"
        # 並不代表每 5 秒發生一次 LINK_DOWN。
        #
        # 只有：
        #
        # up -> down
        #
        # 才是 transition。
        # ----------------------------------------------------

        if (
            current_status
            == old_status
        ):

            continue


        # ====================================================
        # Status Changed
        # ====================================================

        runtime_stats[
            "transitions_detected"
        ] += 1


        runtime_stats[
            "last_transition_at"
        ] = current_time


        # ----------------------------------------------------
        # 先更新 previous
        #
        # 就算 Notification Engine 發生 exception，
        # 下一輪也不會把同一 transition 重複判斷。
        # ----------------------------------------------------

        previous_oper_status[
            entity_key
        ] = current_status


        # ====================================================
        # 只把真正的 up/down transition
        # 轉成 LINK event。
        #
        # testing / unknown 暫不通知。
        # ====================================================

        event_type = None


        if (
            old_status != "down"

            and current_status
            == "down"
        ):

            event_type = (
                "LINK_DOWN"
            )


        elif (
            old_status != "up"

            and current_status
            == "up"
        ):

            event_type = (
                "LINK_UP"
            )


        # ----------------------------------------------------
        # 例如：
        #
        # unknown -> testing
        #
        # 先不處理。
        # ----------------------------------------------------

        if event_type is None:

            continue


        # ====================================================
        # Build Event
        # ====================================================

        event = (
            build_link_event(

                event_type=event_type,

                timestamp=current_time,

                switch_name=switch_name,

                switch_ip=switch_ip,

                interface=interface
            )
        )


        # ====================================================
        # Notification Engine
        # ====================================================

        try:

            decision = (
                notification_engine
                .process_link_event(
                    event
                )
            )


            decisions.append(
                decision
            )


            store_decision(
                decision
            )


        except Exception as error:

            # ------------------------------------------------
            # Notification Engine 壞掉
            #
            # 不能讓整個 SNMP Poller 跟著死。
            #
            # 這就是旁掛式設計的重要性。
            # ------------------------------------------------

            print(

                "[Notification Engine Error]",

                interface.get(
                    "name",
                    index
                ),

                error
            )


    # ========================================================
    # Flapping Recovery Tick
    #
    # 即使這一輪沒有 transition，
    #
    # Engine 還是要知道：
    #
    # 「某個 flapping port 已經 180 秒沒再變化」
    #
    # 才能產生 FLAPPING_END。
    # ========================================================

    try:

        tick_decisions = (
            notification_engine.tick(
                now=current_time
            )
        )


        for decision in tick_decisions:

            decisions.append(
                decision
            )


            store_decision(
                decision
            )


    except Exception as error:

        print(
            "[Notification Tick Error]",
            error
        )


    return decisions


# ============================================================
# Runtime API Status
# ============================================================

def get_notification_runtime_status():

    return {

        "runtime": {

            "baseline_initialized":
                baseline_initialized,

            "tracked_interfaces":
                len(
                    previous_oper_status
                ),

            **runtime_stats
        },


        "engine":
            notification_engine.get_status(),


        "recent_decisions":
            list(
                recent_decisions
            )
    }


# ============================================================
# Manual Suppression
#
# 目前 API 還不開放修改。
#
# 先保留 Python function，
# 下一階段再做 Maintenance API / UI。
# ============================================================

def suppress_interface(
    switch_ip,
    interface_index,
    reason="maintenance",
    duration_seconds=None
):

    notification_engine.suppress_interface(

        switch_ip=(
            switch_ip
        ),

        interface_index=(
            interface_index
        ),

        reason=(
            reason
        ),

        duration_seconds=(
            duration_seconds
        )
    )


# ============================================================
# Remove Manual Suppression
# ============================================================

def unsuppress_interface(
    switch_ip,
    interface_index
):

    notification_engine.unsuppress_interface(

        switch_ip=(
            switch_ip
        ),

        interface_index=(
            interface_index
        )
    )

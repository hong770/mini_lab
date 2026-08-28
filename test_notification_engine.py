from notification_engine import (
    NotificationEngine
)


# ============================================================
# 建立測試 Engine
#
# 測試時把時間縮短：
#
# cooldown = 10 秒
# flap window = 30 秒
# 4 次 transition = flapping
# 20 秒穩定 = flapping cleared
# ============================================================

engine = NotificationEngine(

    cooldown_seconds=10,

    flap_window_seconds=30,

    flap_threshold=4,

    flap_clear_seconds=20
)


# ============================================================
# Helper
# ============================================================

def make_event(
    event_type,
    timestamp,
    admin_status="up",
    oper_status="down"
):

    return {

        "event_type":
            event_type,

        "timestamp":
            timestamp,

        "switch_name":
            "CM-SW.lab.local",

        "switch_ip":
            "192.168.10.2",

        "interface_index":
            1,

        "interface_name":
            "Gi1/0/1",

        "admin_status":
            admin_status,

        "oper_status":
            oper_status
    }


def show(
    title,
    decision
):

    print(
        "\n"
        + "=" * 60
    )

    print(
        title
    )

    print(
        "=" * 60
    )

    print(
        decision.to_dict()
    )


# ============================================================
# Test 1
#
# 第一次 LINK_DOWN
#
# 應該 SEND
# ============================================================

decision = engine.process_link_event(

    make_event(
        "LINK_DOWN",
        timestamp=100
    )
)

show(
    "TEST 1 - First LINK_DOWN",
    decision
)


# ============================================================
# Test 2
#
# 5 秒後又 LINK_DOWN
#
# cooldown = 10 秒
#
# 應該 SUPPRESS
# ============================================================

decision = engine.process_link_event(

    make_event(
        "LINK_DOWN",
        timestamp=105
    )
)

show(
    "TEST 2 - LINK_DOWN cooldown",
    decision
)


# ============================================================
# 重新建立 Engine
#
# 避免前面的測試 transition
# 影響 flapping 測試。
# ============================================================

engine = NotificationEngine(

    cooldown_seconds=10,

    flap_window_seconds=30,

    flap_threshold=4,

    flap_clear_seconds=20
)


# ============================================================
# Test 3
#
# 模擬：
#
# DOWN
# UP
# DOWN
# UP
#
# 30 秒內 4 次 transition
#
# 第四次應變成 FLAPPING_START
# ============================================================

events = [

    make_event(
        "LINK_DOWN",
        timestamp=200,
        oper_status="down"
    ),

    make_event(
        "LINK_UP",
        timestamp=205,
        oper_status="up"
    ),

    make_event(
        "LINK_DOWN",
        timestamp=210,
        oper_status="down"
    ),

    make_event(
        "LINK_UP",
        timestamp=215,
        oper_status="up"
    )
]


for index, event in enumerate(
    events,
    start=1
):

    decision = (
        engine.process_link_event(
            event
        )
    )

    show(
        f"TEST 3.{index} - Flapping sequence",
        decision
    )


# ============================================================
# Test 4
#
# 已進入 Flapping
#
# 再 DOWN
#
# 普通 LINK_DOWN 應被壓掉
# ============================================================

decision = engine.process_link_event(

    make_event(
        "LINK_DOWN",
        timestamp=220
    )
)

show(
    "TEST 4 - Event during flapping",
    decision
)


# ============================================================
# Test 5
#
# 最後 transition = 220
#
# 20 秒穩定後
#
# timestamp 241
#
# 應產生 FLAPPING_END
# ============================================================

decisions = (
    engine.tick(
        now=241
    )
)


print(
    "\n"
    + "=" * 60
)

print(
    "TEST 5 - Flapping recovery"
)

print(
    "=" * 60
)


for decision in decisions:

    print(
        decision.to_dict()
    )


# ============================================================
# Test 6
#
# admin down
#
# 管理員 shutdown interface
#
# LINK_DOWN 不通知
# ============================================================

engine = NotificationEngine()


decision = engine.process_link_event(

    make_event(
        "LINK_DOWN",

        timestamp=300,

        admin_status="down",

        oper_status="down"
    )
)

show(
    "TEST 6 - Admin down suppression",
    decision
)


# ============================================================
# Test 7
#
# Manual Maintenance Suppression
# ============================================================

engine = NotificationEngine()


engine.suppress_interface(

    switch_ip="192.168.10.2",

    interface_index=1,

    reason="lab_maintenance"
)


decision = engine.process_link_event(

    make_event(
        "LINK_DOWN",
        timestamp=400
    )
)

show(
    "TEST 7 - Manual suppression",
    decision
)


# ============================================================
# Debug Engine State
# ============================================================

print(
    "\n"
    + "=" * 60
)

print(
    "ENGINE STATUS"
)

print(
    "=" * 60
)

print(
    engine.get_status()
)

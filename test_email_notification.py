import time


from notification_engine import (
    NotificationDecision
)


from notification_dispatcher import (
    dispatch
)


# ============================================================
# 模擬 Notification Engine 已經決定：
#
# SEND
#
# 我們只測：
#
# Dispatcher → SMTP → Email
# ============================================================

decision = NotificationDecision(

    action="SEND",

    notification_type="LINK_DOWN",

    entity_key="192.168.10.2:10101",

    reason="email_test",

    timestamp=time.time(),

    title=(
        "Interface DOWN - Gi1/0/1"
    ),

    message=(

        "Switch: CM-SW.lab.local\n"
        "IP: 192.168.10.2\n"
        "Interface: Gi1/0/1\n"
        "Status: DOWN\n\n"
        "This is a Mini-Lab Email test."
    ),

    event={

        "event_type":
            "LINK_DOWN",

        "switch_name":
            "CM-SW.lab.local",

        "switch_ip":
            "192.168.10.2",

        "interface_index":
            10101,

        "interface_name":
            "Gi1/0/1"
    }
)


# ============================================================
# Dispatch
# ============================================================

try:

    result = dispatch(
        decision
    )


    print(
        "Email Result:"
    )

    print(
        result
    )


except Exception as error:

    print(
        "Email Error:"
    )

    print(
        type(error).__name__,
        error
    )

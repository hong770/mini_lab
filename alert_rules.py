# ============================================================
# alert_rules.py
#
# Interface Alert 規則
#
# Event:
#     所有狀態變化都可以記錄
#
# Alert:
#     只有我們認為重要的 Interface 才產生告警
# ============================================================


# ============================================================
# Interface Alert Rules
#
# enabled:
#     True  = 要產生 Alert
#     False = 只記 Event
#
# severity:
#     CRITICAL
#     WARNING
#     INFO
#
# 注意：
# Gi1/0/1 如果是管理 / uplink，不要拿來做拔線測試。
# ============================================================

INTERFACE_ALERT_RULES = {

    "GigabitEthernet1/0/1": {
        "enabled": True,
        "severity": "CRITICAL",
        "description": "Management / Uplink"
    },

    "GigabitEthernet1/0/2": {
        "enabled": True,
        "severity": "WARNING",
        "description": "Important access port"
    },

    # Lab 測試 Port
    "GigabitEthernet1/0/10": {
        "enabled": True,
        "severity": "WARNING",
        "description": "Lab test port"
    }
}


# ============================================================
# 取得單一 Interface 的 Alert Rule
# ============================================================

def get_interface_alert_rule(
    interface_name
):

    # 沒有特別設定的 Port：
    # 預設不告警。
    #
    # 否則 48 Port Switch 一堆沒插線的 Port
    # 會全部變 Alert。

    default_rule = {
        "enabled": False,
        "severity": "INFO",
        "description": "No alert rule"
    }


    return INTERFACE_ALERT_RULES.get(
        interface_name,
        default_rule
    )


# ============================================================
# 取得全部 Rule
# ============================================================

def get_all_alert_rules():

    return INTERFACE_ALERT_RULES
